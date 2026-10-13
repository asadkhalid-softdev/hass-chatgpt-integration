"""User setup, account reauthentication, and least-privilege options."""

from __future__ import annotations

import json
import re
from uuid import uuid4

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
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
from .const import DOMAIN

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
        return self.async_show_menu(step_id="init", menu_options=["settings", "review"])

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
        if user_input is not None:
            reserved = [
                value.strip()
                for value in user_input.get("new_automation_ids", "").split(",")
                if value.strip()
            ]
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in reserved):
                errors["new_automation_ids"] = "invalid_automation_id"
            else:
                options = dict(user_input)
                options.pop("new_automation_ids", None)
                options["automation_ids"] = sorted(scopes(options, "automation") | set(reserved))
                options["dashboard_paths"] = sorted(scopes(options, "dashboard"))
                return self.async_create_entry(title="", data=options)
        choices, notice = await self.config_entry.runtime_data.administration.choices()
        try:
            token = await self.config_entry.runtime_data.access_token()
            models = await available_models(async_get_clientsession(self.hass), token)
        except (ConnectionError, AuthError, ModelError):
            errors["base"] = "cannot_connect"
            models = [
                {"value": self.config_entry.options["model"], "label": self.config_entry.options["model"]}
            ]
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("model", default=self.config_entry.options["model"]): SelectSelector(
                            SelectSelectorConfig(options=models)
                        ),
                        vol.Required(
                            "control", default=self.config_entry.options.get("control", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "web_search", default=self.config_entry.options.get("web_search", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "administration", default=self.config_entry.options.get("administration", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "automation_ids", default=sorted(scopes(self.config_entry.options, "automation"))
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=choices["automation"], multiple=True, mode=SelectSelectorMode.LIST
                            )
                        ),
                        vol.Required(
                            "dashboard_paths", default=sorted(scopes(self.config_entry.options, "dashboard"))
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=choices["dashboard"], multiple=True, mode=SelectSelectorMode.LIST
                            )
                        ),
                        vol.Optional("new_automation_ids", default=""): TextSelector(),
                    }
                ),
                user_input or {},
            ),
            errors=errors,
            description_placeholders={"discovery_notice": notice},
        )
