"""Exercise actual Home Assistant flow forms and safe defaults."""

import json
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant

from custom_components.chatgpt_assist import config_flow as flow_module
from custom_components.chatgpt_assist.auth import AuthError


async def test_account_flow_models_and_default_no_control(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    flow = flow_module.ChatGPTFlow()
    flow.hass = hass
    flow.handler = "chatgpt_assist"
    flow.context = {"source": "user"}
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    record = {
        "client_id": "issued",
        "subject": "sub",
        "ext_agent_host_id": "laptop",
        "access_token": "signed",
    }
    monkeypatch.setattr(flow_module, "validate_import", AsyncMock(return_value=record))
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "eligible", "label": "Eligible"}])
    )
    try:
        initial = await flow.async_step_user()
        assert initial["step_id"] == "user"
        models = await flow.async_step_user({"credentials": json.dumps({"access_token": "signed"})})
        assert models["step_id"] == "model"
        assert flow.record["ext_agent_host_id"].startswith("urn:uuid:")
        rejected = await flow.async_step_model({"model": "not-available"})
        assert rejected["errors"]["base"] == "invalid_model"
        created = await flow.async_step_model({"model": "eligible"})
        assert created["type"].value == "create_entry"
        assert created["options"] == {"model": "eligible", "control": False}
    finally:
        await hass.async_stop()


async def test_invalid_import_never_discovers_models(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    flow = flow_module.ChatGPTFlow()
    flow.hass = hass
    flow.handler = "chatgpt_assist"
    flow.context = {"source": "user"}
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(flow_module, "validate_import", AsyncMock(side_effect=AuthError("invalid")))
    models = AsyncMock()
    monkeypatch.setattr(flow_module, "available_models", models)
    try:
        result = await flow.async_step_user({"credentials": "{}"})
        assert result["errors"]["base"] == "invalid_auth"
        models.assert_not_awaited()
    finally:
        await hass.async_stop()
