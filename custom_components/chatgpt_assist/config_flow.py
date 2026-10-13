"""User setup, account reauthentication, and least-privilege options."""

from __future__ import annotations

import json
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.storage import Store

from .api import ModelError, available_models
from .auth import AuthError, ConnectionError, validate_import
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
            except ValueError, AuthError:
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
    """Only built-in Assist can be granted; no arbitrary service APIs."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        errors = {}
        try:
            token = await self.config_entry.runtime_data.access_token()
            models = await available_models(async_get_clientsession(self.hass), token)
        except ConnectionError, AuthError, ModelError:
            errors["base"] = "cannot_connect"
            models = [
                {"value": self.config_entry.options["model"], "label": self.config_entry.options["model"]}
            ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("model", default=self.config_entry.options["model"]): SelectSelector(
                        SelectSelectorConfig(options=models)
                    ),
                    vol.Required(
                        "control", default=self.config_entry.options.get("control", False)
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )
