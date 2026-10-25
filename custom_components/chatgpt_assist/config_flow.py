"""User setup, account reauthentication, and least-privilege options."""

from __future__ import annotations

import json
import re
from uuid import uuid4

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import current_request
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.storage import Store

from .administration import AdministrationError, scopes
from .api import ModelError, available_models
from .auth import AuthError, ConnectionError, validate_import
from .compat import schema as vol
from .const import DOMAIN, REASONING_EFFORTS, reasoning_efforts
from .history import choices as history_choices

SETTINGS_SECTIONS = {
    "automations": {
        "automation_ids",
        "automation_apply",
        "select_all_automations",
        "select_none_automations",
        "new_automation_ids",
    },
    "dashboards": {"dashboard_paths", "select_all_dashboards", "select_none_dashboards"},
    "sensors": {"history_entity_ids", "select_all_history", "select_none_history"},
}


def _group_settings(values):
    """Group only the form fields; persisted options remain flat for compatibility."""
    grouped = dict(values)
    for name, fields in SETTINGS_SECTIONS.items():
        grouped[name] = {field: grouped.pop(field) for field in fields if field in grouped}
    return grouped


def _flatten_settings(values):
    """Unpack native sections before validating grants and one-shot bulk actions."""
    flat = dict(values)
    for name, fields in SETTINGS_SECTIONS.items():
        nested = flat.pop(name, {})
        flat.update({field: value for field, value in nested.items() if field in fields})
    return flat


def _sectioned_schema(flat_schema, opened):
    """Keep general settings visible and permission checklists collapsed initially."""
    fields = flat_schema.schema
    grouped_fields = set().union(*SETTINGS_SECTIONS.values())
    top = {key: value for key, value in fields.items() if key.schema not in grouped_fields}
    for name, members in SETTINGS_SECTIONS.items():
        top[vol.Required(name)] = section(
            vol.Schema({key: value for key, value in fields.items() if key.schema in members}),
            {"collapsed": name not in opened},
        )
    return vol.Schema(top)


CREDENTIAL_SCHEMA = vol.Schema(
    {vol.Required("credentials"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


class ChatGPTFlow(ConfigFlow, domain=DOMAIN):
    """Import an independently verified local OAuth grant over the HA admin UI."""

    VERSION = 1

    def __init__(self) -> None:
        self.record = None
        self.models = []

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                raw = user_input["credentials"]
                if len(raw) > 32_000:
                    raise ValueError
                record = json.loads(raw)
                if not isinstance(record, dict):
                    raise ValueError
                self.record = await validate_import(async_get_clientsession(self.hass), record)
                unique_id = self.record["client_id"] + ":" + self.record["subject"]
                await self.async_set_unique_id(unique_id)
                if self.source == "reauth":
                    entry = self._get_reauth_entry()
                    if entry.unique_id != unique_id:
                        return self.async_abort(reason="wrong_account")
                    self.record["ext_agent_host_id"] = entry.data["ext_agent_host_id"]
                else:
                    self._abort_if_unique_id_configured()
                    # The HA runtime has its own stable host ID, independent of the laptop.
                    store = Store(self.hass, 1, DOMAIN + ".host")
                    host = await store.async_load()
                    if not host:
                        host = {"id": "urn:uuid:" + str(uuid4())}
                        await store.async_save(host)
                    self.record["ext_agent_host_id"] = host["id"]
                self.models = await available_models(
                    async_get_clientsession(self.hass), self.record["access_token"]
                )
            except (ValueError, AuthError):
                errors["base"] = "invalid_auth"
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except ModelError:
                errors["base"] = "no_models"
            else:
                if self.source == "reauth":
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=self.record
                    )
                return await self.async_step_model()
        return self.async_show_form(step_id="user", data_schema=CREDENTIAL_SCHEMA, errors=errors)

    async def async_step_model(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input["model"] not in {m["value"] for m in self.models}:
                errors["base"] = "invalid_model"
            else:
                return self.async_create_entry(
                    title="ChatGPT · " + self.record["client_id"][-8:],
                    data=self.record,
                    options={"model": user_input["model"], "control": False},
                )
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {vol.Required("model"): SelectSelector(SelectSelectorConfig(options=self.models))}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ChatGPTOptionsFlow()


class ChatGPTOptionsFlow(OptionsFlow):
    """Review is protected by HA's authenticated administrator options endpoints."""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["settings", "review", "alexa"])

    async def async_step_alexa(self, user_input=None):
        """Voice bridge settings are separate from stable model/chat options."""
        from .alexa import DEFAULT_LIMIT, DEFAULT_SKILL, KEY, URL

        bridge = self.hass.data[KEY]
        entry_id = self.config_entry.entry_id
        settings = bridge.settings.get(entry_id, {})
        errors = {}
        failure = ""
        if user_input is not None:
            request = current_request.get()
            actor = request.get("hass_user") if request is not None else None
            if not actor or not actor.is_admin:
                return self.async_abort(reason="alexa_admin_required")
            try:
                values = {key: user_input[key] for key in ("enabled", "skill_id", "user_id", "limit")}
                await bridge.configure(entry_id, values, user_input.get("device"), user_input.get("target"))
                return self.async_abort(reason="alexa_saved")
            except (ValueError, HomeAssistantError) as err:
                errors["base"] = "alexa_invalid"
                failure = str(err)
        users = [
            {"value": user.id, "label": user.name or user.id}
            for user in await self.hass.auth.async_get_users()
            if user.is_active and not user.system_generated
        ]
        devices = bridge.pairing_choices(entry_id)
        from homeassistant.helpers import entity_registry as er

        targets = [
            {"value": item.entity_id, "label": item.name or item.original_name or item.entity_id}
            for item in er.async_get(self.hass).entities.values()
            if item.platform == "alexa_media" and item.domain == "media_player"
        ]
        fields = {
            vol.Required("enabled", default=settings.get("enabled", False)): BooleanSelector(),
            vol.Required("skill_id", default=settings.get("skill_id", DEFAULT_SKILL)): str,
            vol.Required(
                "user_id", default=settings.get("user_id", users[0]["value"] if users else "")
            ): SelectSelector(SelectSelectorConfig(options=users)),
            vol.Required("limit", default=settings.get("limit", DEFAULT_LIMIT)): vol.All(
                vol.Coerce(int), vol.Range(min=200, max=1000)
            ),
        }
        if devices and targets:
            fields[vol.Optional("device")] = SelectSelector(SelectSelectorConfig(options=devices))
            fields[vol.Optional("target")] = SelectSelector(SelectSelectorConfig(options=targets))
        return self.async_show_form(
            step_id="alexa",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "endpoint": URL,
                "failure": failure,
                "paired": str(len(settings.get("devices", {}))),
            },
        )

    async def async_step_review(self, user_input=None):
        manager = self.config_entry.runtime_data.administration
        if user_input is not None:
            self.proposal_id = user_input["proposal_id"]
            self.rollback = user_input.get("rollback", False)
            return await self.async_step_confirm()
        options = [
            {"value": key, "label": f"{r['kind']} {r['target']} ({r['status']}) · {key}"}
            for key, r in manager.records.items()
        ]
        if not options:
            return self.async_abort(reason="no_proposals")
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema(
                {
                    vol.Required("proposal_id"): SelectSelector(SelectSelectorConfig(options=options)),
                    vol.Required("rollback", default=False): BooleanSelector(),
                }
            ),
        )

    async def async_step_confirm(self, user_input=None):
        manager = self.config_entry.runtime_data.administration
        errors = {}
        if user_input is not None and user_input.get("approve"):
            try:
                request = current_request.get()
                reviewer = request.get("hass_user") if request is not None else None
                if not reviewer or not reviewer.is_admin:
                    raise AdministrationError(
                        "Approval requires the authenticated administrator settings UI."
                    )
                await manager.apply_from_options(
                    self.proposal_id, reviewer_id=reviewer.id, rollback=self.rollback
                )
            except AdministrationError as err:
                errors["base"] = "administration_failed"
                self.failure = str(err)
            except Exception:
                errors["base"] = "administration_failed"
                self.failure = "Validation or storage failed. Check the configuration before retrying."
            else:
                return self.async_abort(
                    reason="configuration_restored" if self.rollback else "configuration_applied"
                )
        try:
            preview = manager.review(self.proposal_id, rollback=self.rollback)
        except AdministrationError:
            return self.async_abort(reason="no_proposals")
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("approve", default=False): BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "preview": preview,
                "operation": "Restore saved backup" if self.rollback else "Apply proposed configuration",
                "failure": getattr(self, "failure", ""),
            },
        )

    async def async_step_settings(self, user_input=None):
        errors = {}
        selected_model = self.config_entry.options["model"]
        choices, notice = await self.config_entry.runtime_data.administration.choices()
        choices["history"] = history_choices(self.hass, self.config_entry.options)
        bulk_fields = {
            "automation_ids": ("select_all_automations", "select_none_automations", "automation"),
            "dashboard_paths": ("select_all_dashboards", "select_none_dashboards", "dashboard"),
            "history_entity_ids": ("select_all_history", "select_none_history", "history"),
        }
        bulk_requested = False
        opened = set()
        if user_input is not None:
            user_input = _flatten_settings(user_input)
            selected_model = user_input.get("model", selected_model)
            if user_input.get("reasoning_effort", "default") not in REASONING_EFFORTS:
                errors["reasoning_effort"] = "invalid_reasoning_effort"
            elif user_input.get("reasoning_effort", "default") not in reasoning_efforts(selected_model):
                errors["reasoning_effort"] = "unsupported_reasoning_effort"
            for field, (select_all, select_none, kind) in bulk_fields.items():
                if user_input.get(select_all) and user_input.get(select_none):
                    errors[select_none] = "conflicting_bulk_selection"
                elif user_input.get(select_all) or user_input.get(select_none):
                    bulk_requested = True
                    opened.update(name for name, fields in SETTINGS_SECTIONS.items() if field in fields)
                    user_input[field] = (
                        sorted(item["value"] for item in choices[kind]) if user_input.get(select_all) else []
                    )
                    if kind == "automation" and user_input.get(select_none):
                        user_input["new_automation_ids"] = ""
            if not errors:
                for select_all, select_none, _ in bulk_fields.values():
                    user_input.pop(select_all, None)
                    user_input.pop(select_none, None)
            reserved = [
                value.strip()
                for value in user_input.get("new_automation_ids", "").split(",")
                if value.strip()
            ]
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in reserved):
                errors["new_automation_ids"] = "invalid_automation_id"
            elif not errors and not bulk_requested:
                options = dict(user_input)
                options.pop("new_automation_ids", None)
                options["automation_ids"] = sorted(scopes(options, "automation") | set(reserved))
                options["dashboard_paths"] = sorted(scopes(options, "dashboard"))
                options["history_entity_ids"] = sorted(set(options.get("history_entity_ids", [])))
                return self.async_create_entry(title="", data=options)
        try:
            token = await self.config_entry.runtime_data.access_token()
            models = await available_models(async_get_clientsession(self.hass), token)
        except (ConnectionError, AuthError, ModelError):
            errors["base"] = "cannot_connect"
            models = [
                {"value": self.config_entry.options["model"], "label": self.config_entry.options["model"]}
            ]
        section_errors = {}
        for field, reason in errors.items():
            group = next((name for name, fields in SETTINGS_SECTIONS.items() if field in fields), field)
            section_errors[group] = reason
            opened.add(group)
        suggested = (
            user_input
            if user_input is not None
            else {
                **self.config_entry.options,
                "automation_ids": sorted(scopes(self.config_entry.options, "automation")),
                "dashboard_paths": sorted(scopes(self.config_entry.options, "dashboard")),
            }
        )
        if suggested.get("reasoning_effort", "default") not in reasoning_efforts(selected_model):
            suggested = {**suggested, "reasoning_effort": "default"}
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                _sectioned_schema(
                    vol.Schema(
                        {
                            vol.Required("model", default=self.config_entry.options["model"]): SelectSelector(
                                SelectSelectorConfig(options=models)
                            ),
                            vol.Required(
                                "reasoning_effort",
                                default=suggested.get("reasoning_effort", "default"),
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=[
                                        {
                                            "value": effort,
                                            "label": {
                                                "default": "Model default",
                                                "none": "None",
                                                "minimal": "Minimal",
                                                "low": "Low",
                                                "medium": "Medium",
                                                "high": "High",
                                                "xhigh": "Extra high",
                                                "max": "Maximum",
                                            }[effort],
                                        }
                                        for effort in reasoning_efforts(selected_model)
                                    ],
                                    mode=SelectSelectorMode.DROPDOWN,
                                )
                            ),
                            vol.Required(
                                "control", default=self.config_entry.options.get("control", False)
                            ): BooleanSelector(),
                            vol.Required(
                                "web_search", default=self.config_entry.options.get("web_search", False)
                            ): BooleanSelector(),
                            vol.Required(
                                "administration",
                                default=self.config_entry.options.get("administration", False),
                            ): BooleanSelector(),
                            vol.Required(
                                "automation_apply",
                                default=self.config_entry.options.get("automation_apply", True),
                            ): BooleanSelector(),
                            vol.Optional("select_all_automations", default=False): BooleanSelector(),
                            vol.Optional("select_none_automations", default=False): BooleanSelector(),
                            vol.Required(
                                "automation_ids",
                                default=sorted(scopes(self.config_entry.options, "automation")),
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=choices["automation"], multiple=True, mode=SelectSelectorMode.LIST
                                )
                            ),
                            vol.Optional("select_all_dashboards", default=False): BooleanSelector(),
                            vol.Optional("select_none_dashboards", default=False): BooleanSelector(),
                            vol.Required(
                                "dashboard_paths",
                                default=sorted(scopes(self.config_entry.options, "dashboard")),
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=choices["dashboard"], multiple=True, mode=SelectSelectorMode.LIST
                                )
                            ),
                            vol.Optional("new_automation_ids", default=""): TextSelector(),
                            vol.Required(
                                "logs_access", default=self.config_entry.options.get("logs_access", True)
                            ): BooleanSelector(),
                            vol.Required(
                                "history_access",
                                default=self.config_entry.options.get("history_access", False),
                            ): BooleanSelector(),
                            vol.Optional("select_all_history", default=False): BooleanSelector(),
                            vol.Optional("select_none_history", default=False): BooleanSelector(),
                            vol.Required(
                                "history_entity_ids",
                                default=self.config_entry.options.get("history_entity_ids", []),
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=choices["history"], multiple=True, mode=SelectSelectorMode.LIST
                                )
                            ),
                        }
                    ),
                    opened,
                ),
                _group_settings(suggested),
            ),
            errors=section_errors,
            description_placeholders={"discovery_notice": notice},
        )
