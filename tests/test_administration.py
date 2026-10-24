"""Real HA storage, tools and options forms; configuration changes need human approval."""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from homeassistant.components.lovelace import LovelaceData
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import LovelaceStorage, LovelaceYAML
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm

from custom_components.chatgpt_assist.administration import (
    Administration,
    AdministrationError,
    ConfigurationAPI,
    ConfigurationTool,
)
from custom_components.chatgpt_assist.compat import schema as vol
from custom_components.chatgpt_assist.compat import schema_to_json
from custom_components.chatgpt_assist.config_flow import ChatGPTOptionsFlow
from tests.settings_form import settings_fields, suggested_settings, validate_settings


@pytest.fixture
async def environment(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    admin = SimpleNamespace(is_admin=True, is_active=True, system_generated=False)
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=admin))
    entry = SimpleNamespace(
        entry_id="test",
        options={
            "administration": True,
            "automation_ids": "morning,new",
            "dashboard_paths": "test-dashboard",
            "model": "test",
            "control": False,
        },
    )
    manager = Administration(hass, entry)
    entry.runtime_data = SimpleNamespace(administration=manager)
    before = {"id": "morning", "alias": "Morning", "triggers": [], "conditions": [], "actions": []}
    (tmp_path / "configuration.yaml").write_text("automation: !include automations.yaml\n")
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before]))
    reloads = []

    async def reload(call):
        reloads.append(call.data)

    hass.services.async_register("automation", "reload", reload)
    dashboard = LovelaceStorage(hass, {"id": "test-dashboard", "url_path": "test-dashboard"})
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode="storage", dashboards={"test-dashboard": dashboard}, resources=None, yaml_dashboards={}
    )
    await dashboard.async_save({"views": [{"title": "Original", "cards": []}]})
    yield hass, entry, manager, before, reloads
    await hass.async_stop()


async def draft_dashboard(manager):
    return (
        await manager.propose(
            "admin", "dashboard", "test-dashboard", json.dumps({"views": [{"title": "Updated", "cards": []}]})
        )
    )["proposal_id"]


async def test_draft_never_applies_real_storage_then_approve_and_restore(environment):
    hass, entry, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    assert (await manager.read("dashboard", "test-dashboard"))["views"][0]["title"] == "Original"
    recovered = Administration(hass, entry)
    await recovered.load()
    assert recovered.records[proposal]["status"] == "pending"
    await manager.apply_from_options(proposal, reviewer_id="admin")
    assert (await manager.read("dashboard", "test-dashboard"))["views"][0]["title"] == "Updated"
    await manager.apply_from_options(proposal, reviewer_id="admin", rollback=True)
    assert (await manager.read("dashboard", "test-dashboard"))["views"][0]["title"] == "Original"
    assert manager.records[proposal]["status"] == "rolled_back"
    with pytest.raises(AdministrationError):
        await manager.apply_from_options(proposal, reviewer_id="admin")


async def test_automation_validation_write_reload_restore_and_create(environment):
    _, _, manager, before, reloads = environment
    updated = {**before, "alias": "Improved morning"}
    proposal = (await manager.propose("admin", "automation", "morning", json.dumps(updated)))["proposal_id"]
    assert await manager.read("automation", "morning") == before
    await manager.apply_from_options(proposal, reviewer_id="admin")
    assert (await manager.read("automation", "morning"))["alias"] == "Improved morning"
    assert reloads == [{}]
    await manager.apply_from_options(proposal, reviewer_id="admin", rollback=True)
    assert await manager.read("automation", "morning") == before
    new = (await manager.propose("admin", "automation", "new", json.dumps({**before, "id": "new"})))[
        "proposal_id"
    ]
    await manager.apply_from_options(new, reviewer_id="admin")
    assert (await manager.read("automation", "new"))["id"] == "new"
    await manager.apply_from_options(new, reviewer_id="admin", rollback=True)
    assert await manager.read("automation", "new") is None
    assert await manager.read("automation", "morning") == before


@pytest.mark.parametrize(
    "admin,active,system,user_id",
    [
        (False, True, False, "user"),
        (True, False, False, "user"),
        (True, True, True, "system"),
        (True, True, False, None),
    ],
)
async def test_configuration_tools_deny_untrusted_identity(environment, admin, active, system, user_id):
    hass, _, manager, _, _ = environment
    hass.auth.async_get_user.return_value = SimpleNamespace(
        is_admin=admin, is_active=active, system_generated=system
    )
    with pytest.raises(AdministrationError):
        await manager.authorize(user_id)
    assert not manager.records


@pytest.mark.parametrize("change", ["disable", "revoke", "expired", "tampered", "scope", "conflict"])
async def test_approval_fails_closed_without_writing(environment, change):
    hass, entry, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    if change == "disable":
        entry.options["administration"] = False
    elif change == "revoke":
        hass.auth.async_get_user.return_value.is_admin = False
    elif change == "expired":
        manager.records[proposal]["expires"] = time.time() - 1
    elif change == "tampered":
        manager.records[proposal]["after"]["views"][0]["title"] = "tampered"
    elif change == "scope":
        entry.options["dashboard_paths"] = ""
    else:
        await manager._dashboard("test-dashboard").async_save({"views": [{"title": "Human edit"}]})
    with pytest.raises(AdministrationError):
        await manager.apply_from_options(proposal, reviewer_id="admin")
    title = (await manager._dashboard("test-dashboard").async_load(False))["views"][0]["title"]
    assert title == ("Human edit" if change == "conflict" else "Original")


async def test_real_tool_schemas_no_model_approval_and_context(environment):
    hass, entry, manager, _, _ = environment
    entry.options.update({"automation_apply": False, "logs_access": False})
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="admin"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    api = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert {tool.name for tool in api.tools} == {
        "configuration_list",
        "configuration_read",
        "configuration_propose",
        "configuration_status",
    }
    for tool in api.tools:
        json.dumps(schema_to_json(tool.parameters, custom_serializer=api.custom_serializer))
    tool = ConfigurationTool(manager, "propose")
    with pytest.raises(vol.Invalid):
        tool.parameters(
            {"kind": "dashboard", "target": "test-dashboard", "config_json": "{}", "approve": True}
        )
    read = ConfigurationTool(manager, "read")
    result = await read.async_call(
        hass,
        llm.ToolInput(tool_name=read.name, tool_args={"kind": "automation", "target": "morning"}),
        context,
    )
    assert (result.data if hasattr(result, "data") else result)["configuration"]["triggers"] == []
    hass.auth.async_get_user.assert_awaited_with("admin")


async def test_options_review_requires_checkbox_and_uses_server_draft(environment, monkeypatch):
    hass, entry, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    menu = await flow.async_step_init()
    assert menu["menu_options"] == ["settings", "review", "alexa"]
    review = await flow.async_step_review({"proposal_id": proposal, "rollback": False})
    assert "Original" in review["description_placeholders"]["preview"]
    assert "Updated" in review["description_placeholders"]["preview"]
    await flow.async_step_confirm({"approve": False})
    assert manager.records[proposal]["status"] == "pending"
    # Production uses the user from the real HTTP request, not a user-supplied flow value.
    from homeassistant.helpers.http import current_request

    token = current_request.set({"hass_user": SimpleNamespace(id="admin", is_admin=True)})
    try:
        applied = await flow.async_step_confirm({"approve": True})
    finally:
        current_request.reset(token)
    assert applied["reason"] == "configuration_applied"


async def test_invalid_config_scope_blueprints_yaml_and_secrets_never_write(environment, tmp_path):
    hass, _, manager, before, _ = environment
    for kind, target, config in [
        ("automation", "not-granted", before),
        ("automation", "morning", {**before, "id": "../../other"}),
        ("automation", "morning", {"id": "morning", "triggers": "invalid"}),
        ("automation", "morning", {**before, "use_blueprint": {"path": "test"}}),
        ("dashboard", "test-dashboard", {"views": "invalid"}),
        ("dashboard", "test-dashboard", {"views": [], "resources": []}),
    ]:
        with pytest.raises(AdministrationError):
            await manager.propose("admin", kind, target, json.dumps(config))
    assert not manager.records
    original = (tmp_path / "automations.yaml").read_text()
    (tmp_path / "automations.yaml").write_text("- id: morning\n  secret: !secret password\n")
    with pytest.raises(AdministrationError):
        await manager.propose("admin", "automation", "morning", json.dumps(before))
    assert "!secret" in (tmp_path / "automations.yaml").read_text()
    (tmp_path / "automations.yaml").write_text(original)
    hass.data[LOVELACE_DATA].dashboards["test-dashboard"] = LovelaceYAML(
        hass, "test-dashboard", {"filename": "dashboard.yaml"}
    )
    with pytest.raises(AdministrationError):
        await manager.read("dashboard", "test-dashboard")


async def test_backup_persisted_before_write_failure_and_recovery(environment, monkeypatch):
    hass, entry, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    original = manager._write

    async def fail_after_write(record, config, expected, *, rollback=False):
        recovered = Administration(hass, entry)
        await recovered.load()
        assert recovered.records[proposal]["before"]["views"][0]["title"] == "Original"
        assert recovered.records[proposal]["status"] == "applying"
        await original(record, config, expected, rollback=rollback)
        raise OSError("never expose internal secret")

    monkeypatch.setattr(manager, "_write", fail_after_write)
    with pytest.raises(AdministrationError, match="saved backup"):
        await manager.apply_from_options(proposal, reviewer_id="admin")
    assert manager.records[proposal]["status"] == "failed"
    monkeypatch.setattr(manager, "_write", original)
    await manager.apply_from_options(proposal, reviewer_id="admin", rollback=True)
    assert manager.records[proposal]["status"] == "rolled_back"


async def test_restore_preserves_later_edits_and_drafts_expire(environment):
    _, _, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    await manager.apply_from_options(proposal, reviewer_id="admin")
    await manager._dashboard("test-dashboard").async_save({"views": [{"title": "Later edit"}]})
    with pytest.raises(AdministrationError):
        await manager.apply_from_options(proposal, reviewer_id="admin", rollback=True)
    assert (await manager.read("dashboard", "test-dashboard"))["views"][0]["title"] == "Later edit"


async def test_ha_options_endpoint_denies_non_admin():
    """The approval UI's actual Core HTTP boundary rejects non-admin submissions."""
    from homeassistant.components.config.config_entries import OptionManagerFlowResourceView
    from homeassistant.exceptions import Unauthorized

    flow_manager = AsyncMock()
    view = OptionManagerFlowResourceView(flow_manager)
    request = {"hass_user": SimpleNamespace(is_admin=False)}
    with pytest.raises(Unauthorized):
        await view.post(request, "flow-id")
    flow_manager.async_configure.assert_not_called()


async def test_administration_chat_rejects_non_admin_before_provider(environment, monkeypatch):
    from homeassistant.components import conversation

    from custom_components.chatgpt_assist import conversation as agent

    hass, entry, _, _, _ = environment
    hass.auth.async_get_user.return_value.is_admin = False
    entity = agent.ChatGPTConversation(entry)
    entity.hass = hass
    entity.entity_id = "conversation.test"
    user = conversation.ConversationInput(
        text="hi",
        context=Context(user_id="guest"),
        conversation_id="protected",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    provider = AsyncMock()
    monkeypatch.setattr(agent, "response", provider)
    result = await entity._handle(user, SimpleNamespace(conversation_id="protected", content=[]))
    assert result.response.response_type.value == "error"
    provider.assert_not_called()


@pytest.mark.parametrize("web_search", [False, True])
async def test_real_admin_conversation_proposes_without_applying(environment, monkeypatch, web_search):
    from homeassistant.components import conversation

    from custom_components.chatgpt_assist import conversation as agent
    from custom_components.chatgpt_assist.const import NAMESPACE

    hass, entry, manager, _, _ = environment
    entry.options["web_search"] = web_search
    entry.runtime_data.session = None
    entry.runtime_data.access_token = AsyncMock(return_value="fake-access")
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="Prepare a dashboard edit",
        context=Context(user_id="admin"),
        conversation_id="draft-test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "draft-test")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    # Build the real per-entry API and let the real ChatLog dispatch its tool.
    async def provide(self, context, selected, prompt, extra):
        assert isinstance(selected, ConfigurationAPI)
        self.llm_api = await selected.async_get_api_instance(context)
        self.content[0] = conversation.SystemContent(content=prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    responses = AsyncMock(
        side_effect=[
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "configuration_propose",
                        "namespace": NAMESPACE,
                        "call_id": "draft-call",
                        "arguments": json.dumps(
                            {
                                "kind": "dashboard",
                                "target": "test-dashboard",
                                "config_json": json.dumps({"views": [{"title": "Drafted"}]}),
                            }
                        ),
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Draft ready for review."}],
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(agent, "response", responses)
    result = await entity._async_handle_message(user, log)
    assert result.response.speech["plain"]["speech"] == "Draft ready for review."
    assert next(iter(manager.records.values()))["status"] == "pending"
    assert (await manager.read("dashboard", "test-dashboard"))["views"][0]["title"] == "Original"
    returned = json.loads(responses.call_args.args[3][-1]["output"])
    assert returned["status"] == "pending"
    assert "proposal_id" in returned
    assert [tool["type"] for tool in responses.call_args.args[4]] == (
        ["namespace", "web_search"] if web_search else ["namespace"]
    )


async def test_approval_without_authenticated_ui_request_is_rejected(environment, monkeypatch):
    hass, entry, manager, _, _ = environment
    proposal = await draft_dashboard(manager)
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    await flow.async_step_review({"proposal_id": proposal, "rollback": False})
    result = await flow.async_step_confirm({"approve": True})
    assert result["errors"]["base"] == "administration_failed"
    assert manager.records[proposal]["status"] == "pending"


async def test_real_automation_integration_reloads_and_removes_created_automation(tmp_path):
    """Verify the actual Core reload service updates entities, not only the saved file."""
    from homeassistant import loader
    from homeassistant.auth import auth_manager_from_config
    from homeassistant.components.automation import DATA_COMPONENT
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.helpers import area_registry, device_registry, entity_registry
    from homeassistant.setup import async_setup_component

    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    if hasattr(device_registry, "async_setup"):
        device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    await area_registry.async_load(hass)
    hass.auth = await auth_manager_from_config(hass, [], [])
    user = await hass.auth.async_create_user("Configuration test administrator")
    before = {"id": "probe", "alias": "Original probe", "triggers": [], "conditions": [], "actions": []}
    (tmp_path / "configuration.yaml").write_text("automation: !include automations.yaml\n")
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before]))
    try:
        assert await async_setup_component(hass, "automation", {"automation": [before]})
        await hass.async_block_till_done()
        entry = SimpleNamespace(
            entry_id="probe", options={"administration": True, "automation_ids": "probe,new"}
        )
        manager = Administration(hass, entry)
        changed = (
            await manager.propose(
                user.id, "automation", "probe", json.dumps({**before, "alias": "Updated probe"})
            )
        )["proposal_id"]
        await manager.apply_from_options(changed, reviewer_id=user.id)
        await hass.async_block_till_done()
        assert [entity.name for entity in hass.data[DATA_COMPONENT].entities] == ["Updated probe"]
        await manager.apply_from_options(changed, reviewer_id=user.id, rollback=True)
        await hass.async_block_till_done()
        assert [entity.name for entity in hass.data[DATA_COMPONENT].entities] == ["Original probe"]
        created = (
            await manager.propose(
                user.id, "automation", "new", json.dumps({**before, "id": "new", "alias": "New probe"})
            )
        )["proposal_id"]
        await manager.apply_from_options(created, reviewer_id=user.id)
        await hass.async_block_till_done()
        assert {entity.unique_id for entity in hass.data[DATA_COMPONENT].entities} == {"probe", "new"}
        await manager.apply_from_options(created, reviewer_id=user.id, rollback=True)
        await hass.async_block_till_done()
        assert {entity.unique_id for entity in hass.data[DATA_COMPONENT].entities} == {"probe"}
        # A different include must still populate the checklist from real loaded entities.
        (tmp_path / "custom_automations.yaml").write_text(yaml.safe_dump([before]))
        (tmp_path / "configuration.yaml").write_text("automation: !include custom_automations.yaml\n")
        await hass.services.async_call(
            "automation", "reload", blocking=True, context=Context(user_id=user.id)
        )
        await hass.async_block_till_done()
        choices, notice = await manager.choices()
        assert any(
            item["value"] == "probe" and "read only" in item["label"] for item in choices["automation"]
        )
        assert "editor access is unavailable" in notice
        assert (await manager.read("automation", "probe"))["alias"] == "Original probe"
    finally:
        await hass.async_stop()


async def test_disabling_administration_does_not_resend_sensitive_history(environment, monkeypatch):
    from homeassistant.components import conversation

    from custom_components.chatgpt_assist import conversation as agent

    hass, entry, _, _, _ = environment
    entry.options["administration"] = False
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="hi",
        context=Context(user_id="guest"),
        conversation_id="private",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    history = conversation.ToolResultContent(
        agent_id=entity.entity_id,
        tool_name="configuration_read",
        tool_call_id="private-result",
        **(
            {"result": llm.ToolResult(data={"configuration": "private"})}
            if hasattr(llm, "ToolResult")
            else {"tool_result": {"configuration": "private"}}
        ),
    )
    provider = AsyncMock()
    monkeypatch.setattr(agent, "response", provider)
    result = await entity._handle(user, SimpleNamespace(conversation_id="private", content=[history]))
    assert result.response.response_type.value == "error"
    provider.assert_not_called()


async def test_reasoning_options_preserve_defaults_save_and_validate(environment, monkeypatch):
    from custom_components.chatgpt_assist import config_flow as flow_module
    from custom_components.chatgpt_assist.const import REASONING_EFFORTS

    hass, entry, _, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    values = validate_settings(form, {})
    assert values["reasoning_effort"] == "default"
    fields = {key.schema: value for key, value in settings_fields(form).items()}
    assert [choice["value"] for choice in fields["reasoning_effort"].config["options"]] == list(
        REASONING_EFFORTS
    )
    original_grants = {
        key: values[key] for key in ("automation_ids", "dashboard_paths", "history_entity_ids")
    }
    saved = await flow.async_step_settings(validate_settings(form, {"reasoning_effort": "low"}))
    assert saved["data"]["reasoning_effort"] == "low"
    assert all(saved["data"][key] == value for key, value in original_grants.items())
    entry.options.update(saved["data"])
    reopened = await flow.async_step_settings()
    assert suggested_settings(reopened)["reasoning_effort"] == "low"
    with pytest.raises(vol.Invalid):
        validate_settings(reopened, {"reasoning_effort": "ultra"})
    invalid = await flow.async_step_settings({**values, "reasoning_effort": "ultra"})
    assert invalid["errors"]["reasoning_effort"] == "invalid_reasoning_effort"


async def test_permissions_checklists_discover_names_and_preserve_grants(environment, monkeypatch):
    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, manager, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    manager._dashboard("test-dashboard").config["title"] = "Family dashboard"
    # A missing dashboard remains visible rather than silently losing its permission.
    entry.options["dashboard_paths"] += ",missing-dashboard"
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    defaults = validate_settings(form, {})
    assert defaults["automation_ids"] == ["morning", "new"]
    assert defaults["dashboard_paths"] == ["missing-dashboard", "test-dashboard"]
    # Validate the actual form schema and inspect Core's serialized select selectors.
    from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView

    schema = _BaseFlowManagerView(None)._prepare_result_json(form)["data_schema"]
    json.dumps(schema)
    fields = {key.schema: value for key, value in settings_fields(form).items()}
    automations = fields["automation_ids"].config
    dashboards = fields["dashboard_paths"].config
    assert automations["mode"] == "list" and automations["multiple"] is True
    assert dashboards["mode"] == "list" and dashboards["multiple"] is True
    assert {item["value"]: item["label"] for item in automations["options"]} == {
        "morning": "Morning · morning",
        "new": "Reserved or unavailable automation · new",
    }
    assert "Family dashboard" in next(
        item["label"] for item in dashboards["options"] if item["value"] == "test-dashboard"
    )
    saved = await flow.async_step_settings(
        validate_settings(
            form,
            {
                "model": "test",
                "control": False,
                "administration": True,
                "automation_ids": ["morning"],
                "dashboard_paths": [],
                "new_automation_ids": "future_lights",
            },
        )
    )
    assert saved["data"]["automation_ids"] == ["future_lights", "morning"]
    assert saved["data"]["dashboard_paths"] == []
    assert "new_automation_ids" not in saved["data"]
    with pytest.raises(vol.Invalid):
        validate_settings(form, {"automation_ids": ["not-discovered-or-granted"]})


async def test_discovery_failure_preserves_existing_selections_and_explains(environment, tmp_path):
    hass, _, manager, _, _ = environment
    (tmp_path / "automations.yaml").write_text("bad: structure\n")
    hass.data.pop(LOVELACE_DATA)
    choices, notice = await manager.choices()
    assert {item["value"] for item in choices["automation"]} == {"morning", "new"}
    assert {item["value"] for item in choices["dashboard"]} == {"test-dashboard"}
    assert "Automation editor access is unavailable" in notice
    assert "Dashboard discovery is unavailable" in notice


@pytest.mark.parametrize("stored", [" morning, new ", ["morning", "new"], ["morning", " new ", "morning"]])
async def test_legacy_and_list_permissions_enforce_same_targets(environment, stored):
    _, entry, manager, _, _ = environment
    entry.options["automation_ids"] = stored
    manager.permitted("automation", "morning")
    manager.permitted("automation", "new")
    with pytest.raises(AdministrationError):
        manager.permitted("automation", "unselected")


async def test_discovered_items_are_not_automatically_granted_or_shared(environment, tmp_path):
    hass, entry, manager, before, _ = environment
    (tmp_path / "automations.yaml").write_text(
        yaml.safe_dump([before, {**before, "id": "private", "alias": "Private automation"}])
    )
    choices, _ = await manager.choices()
    assert "private" in {item["value"] for item in choices["automation"]}
    with pytest.raises(AdministrationError):
        manager.permitted("automation", "private")
    tool = ConfigurationTool(manager, "list")
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="admin"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    result = await tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args={}), context)
    data = result.data if hasattr(result, "data") else result
    assert data["names"]["automation"]["morning"] == "Morning · morning"
    assert "Private automation" not in json.dumps(data)
    assert "private" not in data["automation"]


async def test_invalid_creation_id_keeps_settings_form_open(environment, monkeypatch):
    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, _, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    result = await flow.async_step_settings(
        {
            "model": "test",
            "control": False,
            "administration": True,
            "automation_ids": ["morning"],
            "dashboard_paths": [],
            "new_automation_ids": "../../bad",
        }
    )
    assert result["errors"]["automations"] == "invalid_automation_id"
    assert entry.options["automation_ids"] == "morning,new"


async def test_empty_catalog_has_no_default_grants_and_explains_next_step(environment, tmp_path, monkeypatch):
    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, manager, _, _ = environment
    entry.options.pop("automation_ids")
    entry.options.pop("dashboard_paths")
    (tmp_path / "automations.yaml").write_text("[]\n")
    hass.data[LOVELACE_DATA].dashboards.clear()
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    defaults = validate_settings(form, {})
    assert defaults["automation_ids"] == []
    assert defaults["dashboard_paths"] == []
    assert "No automations" in form["description_placeholders"]["discovery_notice"]
    assert "No storage-mode dashboards" in form["description_placeholders"]["discovery_notice"]
    assert not manager.records


async def test_loaded_automation_discovery_and_secret_safe_read_without_standard_include(
    environment, tmp_path
):
    from homeassistant.components.automation import DATA_COMPONENT
    from homeassistant.util.yaml import Secrets, load_yaml

    hass, entry, manager, _, _ = environment
    source = tmp_path / "packages" / "lights.yaml"
    source.parent.mkdir()
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  packages: !include_dir_named packages\n")
    (tmp_path / "secrets.yaml").write_text("webhook: TOP_SECRET_DO_NOT_SEND\n")
    source.write_text(
        "automation:\n  - id: package_lights\n    alias: Package lights\n    triggers:\n      - trigger: webhook\n        webhook_id: !secret webhook\n    actions: []\n"
    )
    raw = load_yaml(str(source), Secrets(tmp_path))["automation"][0]
    assert raw["triggers"][0]["webhook_id"] == "TOP_SECRET_DO_NOT_SEND"
    entity = SimpleNamespace(
        unique_id="package_lights",
        entity_id="automation.package_lights",
        name="Package lights",
        raw_config=raw,
    )
    hass.data[DATA_COMPONENT] = SimpleNamespace(entities=[entity])
    choices, notice = await manager.choices()
    choice = next(item for item in choices["automation"] if item["value"] == "package_lights")
    assert "Package lights" in choice["label"] and "read only" in choice["label"]
    assert "Only automation:" in notice
    entry.options["automation_ids"] = ["package_lights"]
    config = await manager.read("automation", "package_lights")
    assert config["triggers"][0]["webhook_id"] == {"yaml_tag": "!secret", "reference": "webhook"}
    assert "TOP_SECRET_DO_NOT_SEND" not in json.dumps(config)
    with pytest.raises(AdministrationError, match="editing is unavailable"):
        await manager.propose(
            "admin", "automation", "package_lights", json.dumps({**config, "alias": "Changed"})
        )
    assert not manager.records


async def test_loaded_automation_without_id_is_selectable_and_read_only(environment, tmp_path):
    from homeassistant.components.automation import DATA_COMPONENT
    from homeassistant.util.yaml import load_yaml

    hass, entry, manager, _, _ = environment
    source = tmp_path / "package.yaml"
    source.write_text("automation:\n  - alias: No ID automation\n    triggers: []\n    actions: []\n")
    raw = load_yaml(str(source))["automation"][0]
    entity = SimpleNamespace(
        unique_id=None, entity_id="automation.no_id", name="No ID automation", raw_config=raw
    )
    hass.data[DATA_COMPONENT] = SimpleNamespace(entities=[entity])
    choices, _ = await manager.choices()
    assert any(item["value"] == "automation.no_id" for item in choices["automation"])
    entry.options["automation_ids"] = ["automation.no_id"]
    assert (await manager.read("automation", "automation.no_id"))["alias"] == "No ID automation"
    with pytest.raises(AdministrationError, match="read only"):
        await manager.propose(
            "admin", "automation", "automation.no_id", json.dumps({**raw, "alias": "Changed"})
        )


async def test_source_inspection_rejects_stale_location_and_external_path(environment, tmp_path):
    from homeassistant.components.automation import DATA_COMPONENT
    from homeassistant.util.yaml import load_yaml

    hass, entry, manager, _, _ = environment
    source = tmp_path / "package.yaml"
    source.write_text("- id: package\n  alias: Original\n  triggers: []\n  actions: []\n")
    raw = load_yaml(str(source))[0]
    entity = SimpleNamespace(
        unique_id="package", entity_id="automation.package", name="Original", raw_config=raw
    )
    hass.data[DATA_COMPONENT] = SimpleNamespace(entities=[entity])
    entry.options["automation_ids"] = ["package"]
    source.write_text("- id: other\n  alias: Changed\n  triggers: []\n  actions: []\n")
    with pytest.raises(AdministrationError, match="changed since loading"):
        await manager.read("automation", "package")
    raw.__config_file__ = str(tmp_path.parent / "outside.yaml")
    with pytest.raises(AdministrationError, match="outside"):
        await manager.read("automation", "package")


async def test_equivalent_standard_include_and_non_json_yaml_diagnostics(environment, tmp_path):
    _, _, manager, _, _ = environment
    (tmp_path / "configuration.yaml").write_text("automation: !include ./automations.yaml\n")
    assert (await manager.read("automation", "morning"))["alias"] == "Morning"
    (tmp_path / "automations.yaml").write_text("- id: morning\n  alias: Morning\n  date: 2026-10-13\n")
    _, notice = await manager.choices()
    assert "not JSON compatible" in notice


@pytest.mark.parametrize(
    "unsafe",
    ["    actions: &loop [*loop]\n", "    actions: []\n    actions: []\n", "    <<: {actions: []}\n"],
)
async def test_read_only_source_rejects_ambiguous_or_recursive_yaml(environment, tmp_path, unsafe):
    from homeassistant.components.automation import DATA_COMPONENT
    from homeassistant.util.yaml import load_yaml

    hass, entry, manager, _, _ = environment
    source = tmp_path / "package.yaml"
    header = "automation:\n  - id: package\n    alias: Package\n"
    source.write_text(header + "    actions: []\n")
    raw = load_yaml(str(source))["automation"][0]
    entity = SimpleNamespace(
        unique_id="package", entity_id="automation.package", name="Package", raw_config=raw
    )
    hass.data[DATA_COMPONENT] = SimpleNamespace(entities=[entity])
    entry.options["automation_ids"] = ["package"]
    source.write_text(header + unsafe)
    with pytest.raises(AdministrationError):
        await manager.read("automation", "package")


@pytest.mark.parametrize(
    ("automation_action", "dashboard_action", "expected_automations", "expected_dashboards"),
    [
        ("all", "all", ["morning", "new"], ["test-dashboard"]),
        ("none", "none", [], []),
        ("all", "none", ["morning", "new"], []),
        ("none", "all", [], ["test-dashboard"]),
    ],
)
async def test_bulk_permissions_are_reviewed_before_saving(
    environment,
    monkeypatch,
    automation_action,
    dashboard_action,
    expected_automations,
    expected_dashboards,
):
    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, _, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    submitted = validate_settings(
        form,
        {
            "model": "test",
            "control": True,
            "web_search": True,
            "administration": True,
            "automation_ids": [],
            "dashboard_paths": [],
            "new_automation_ids": "future_lights",
            f"select_{automation_action}_automations": True,
            f"select_{dashboard_action}_dashboards": True,
        },
    )
    result = await flow.async_step_settings(submitted)
    assert result["type"] == "form"
    assert result["errors"] == {}
    # Suggested values are what the frontend checks when redisplaying a form.
    suggested = suggested_settings(result)
    assert suggested["automation_ids"] == expected_automations
    assert suggested["dashboard_paths"] == expected_dashboards
    assert suggested["control"] is True and suggested["web_search"] is True
    assert suggested["new_automation_ids"] == ("" if automation_action == "none" else "future_lights")
    assert not any(name.startswith("select_") for name in suggested)
    assert entry.options["automation_ids"] == "morning,new"
    # The user may narrow the refreshed selections before saving.
    suggested["automation_ids"] = expected_automations[:1]
    saved = await flow.async_step_settings(validate_settings(result, suggested))
    reserved = [] if automation_action == "none" else ["future_lights"]
    assert saved["data"]["automation_ids"] == sorted(expected_automations[:1] + reserved)
    assert saved["data"]["dashboard_paths"] == expected_dashboards
    assert not any(name.startswith("select_") for name in saved["data"])


async def test_conflicting_bulk_permissions_keep_form_and_existing_grants(environment, monkeypatch):
    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, _, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    result = await flow.async_step_settings(
        {
            "model": "test",
            "automation_ids": ["morning"],
            "dashboard_paths": [],
            "select_all_automations": True,
            "select_none_automations": True,
            "select_all_dashboards": True,
            "select_none_dashboards": True,
        }
    )
    assert result["errors"] == {
        "automations": "conflicting_bulk_selection",
        "dashboards": "conflicting_bulk_selection",
    }
    assert entry.options["automation_ids"] == "morning,new"
    assert entry.options["dashboard_paths"] == "test-dashboard"


async def test_native_permission_sections_start_closed_and_save_existing_flat_grants(
    environment, monkeypatch
):
    from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView

    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, _, _, _ = environment
    entry.options["history_entity_ids"] = ["sensor.temperature"]
    entry.options["history_access"] = True
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    frontend = _BaseFlowManagerView(None)._prepare_result_json(form)
    json.dumps(frontend)
    sections = {
        field["name"]: field for field in frontend["data_schema"] if field.get("type") == "expandable"
    }
    assert set(sections) == {"automations", "dashboards", "sensors"}
    assert all(not field["expanded"] for field in sections.values())
    assert {field["name"] for field in sections["automations"]["schema"]} == {
        "automation_ids",
        "automation_apply",
        "select_all_automations",
        "select_none_automations",
        "new_automation_ids",
    }
    # Unchanged native sections retain grants, including unavailable saved targets.
    nested = form["data_schema"]({"automations": {}, "dashboards": {}, "sensors": {}})
    saved = await flow.async_step_settings(nested)
    assert saved["data"]["automation_ids"] == ["morning", "new"]
    assert saved["data"]["dashboard_paths"] == ["test-dashboard"]
    assert saved["data"]["history_entity_ids"] == ["sensor.temperature"]
    assert not {"automations", "dashboards", "sensors"} & saved["data"].keys()
    # Missing sections fail form validation instead of silently erasing permissions.
    with pytest.raises(vol.Invalid):
        form["data_schema"]({"model": "test"})
    fields = {key.schema: value for key, value in form["data_schema"].schema.items()}
    assert fields["automations"].schema({})["automation_ids"] == ["morning", "new"]


async def test_bulk_review_and_validation_open_only_affected_native_sections(environment, monkeypatch):
    from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView

    from custom_components.chatgpt_assist import config_flow as flow_module

    hass, entry, _, _, _ = environment
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    result = await flow.async_step_settings(
        form["data_schema"](
            {
                "automations": {"select_none_automations": True},
                "dashboards": {},
                "sensors": {},
            }
        )
    )
    sections = {
        field["name"]: field
        for field in _BaseFlowManagerView(None)._prepare_result_json(result)["data_schema"]
        if field.get("type") == "expandable"
    }
    assert sections["automations"]["expanded"] is True
    assert sections["dashboards"]["expanded"] is False and sections["sensors"]["expanded"] is False
    checkbox = next(field for field in sections["automations"]["schema"] if field["name"] == "automation_ids")
    assert checkbox["description"]["suggested_value"] == []
    result = await flow.async_step_settings(
        form["data_schema"](
            {
                "automations": {"new_automation_ids": "../../invalid"},
                "dashboards": {},
                "sensors": {},
            }
        )
    )
    assert result["errors"] == {"automations": "invalid_automation_id"}
    sections = {
        key.schema: value
        for key, value in result["data_schema"].schema.items()
        if key.schema in {"automations", "dashboards", "sensors"}
    }
    assert sections["automations"].options["collapsed"] is False
    assert entry.options["automation_ids"] == "morning,new"


async def test_unrelated_duplicate_ids_do_not_block_unique_edit(environment, tmp_path):
    _, _, manager, before, _ = environment
    (tmp_path / "automations.yaml").write_text(
        yaml.safe_dump(
            [
                before,
                {**before, "id": "duplicate", "alias": "Unselected first"},
                {**before, "id": "duplicate", "alias": "Unselected second"},
            ]
        )
    )
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**before, "alias": "Updated"})
    )
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin")
    values = yaml.safe_load((tmp_path / "automations.yaml").read_text())
    assert values[0]["alias"] == "Updated"
    assert [value["alias"] for value in values[1:]] == ["Unselected first", "Unselected second"]
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin", rollback=True)
    assert yaml.safe_load((tmp_path / "automations.yaml").read_text())[0] == before


async def test_duplicate_entries_are_inspectable_and_surgical_updates_restore(environment, tmp_path):
    _, _, manager, before, _ = environment
    second = {**before, "alias": "Second humidity rule"}
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before, second]))
    entries = await manager.automation_entries()
    assert [item["entry_index"] for item in entries] == [0, 1]
    assert all(item["duplicate_id"] for item in entries)
    inspected = await manager.read("automation", "morning")
    assert inspected["duplicate_id"] == "morning" and len(inspected["entries"]) == 2
    assert await manager.read("automation", "morning", 1) == second
    with pytest.raises(AdministrationError, match="entry_index"):
        await manager.propose("admin", "automation", "morning", json.dumps({**second, "alias": "Changed"}))
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**second, "alias": "Changed"}), entry_index=1
    )
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin")
    values = yaml.safe_load((tmp_path / "automations.yaml").read_text())
    assert values[0] == before and values[1]["alias"] == "Changed"
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin", rollback=True)
    assert yaml.safe_load((tmp_path / "automations.yaml").read_text()) == [before, second]


async def test_duplicate_id_can_be_repaired_and_undone_without_touching_other_entry(environment, tmp_path):
    _, _, manager, before, _ = environment
    second = {**before, "alias": "Second"}
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before, second]))
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**second, "id": "unique_second"}), entry_index=1
    )
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin")
    values = yaml.safe_load((tmp_path / "automations.yaml").read_text())
    assert values[0] == before and values[1]["id"] == "unique_second"
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin", rollback=True)
    assert yaml.safe_load((tmp_path / "automations.yaml").read_text()) == [before, second]


async def test_duplicate_index_reordering_blocks_stale_draft(environment, tmp_path):
    _, _, manager, before, _ = environment
    second = {**before, "alias": "Second"}
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before, second]))
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**second, "alias": "Changed"}), entry_index=1
    )
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([second, before]))
    with pytest.raises(AdministrationError, match="changed"):
        await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin")
    assert yaml.safe_load((tmp_path / "automations.yaml").read_text()) == [second, before]


async def test_direct_apply_and_restore_tools_are_admin_scoped_and_dashboard_review_stays(environment):
    hass, entry, manager, before, _ = environment
    entry.options["logs_access"] = False
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="admin"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    api = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert {"configuration_apply", "configuration_restore"} <= {tool.name for tool in api.tools}
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**before, "alias": "Direct update"})
    )
    apply = ConfigurationTool(manager, "apply")
    arguments = llm.ToolInput(tool_name=apply.name, tool_args={"proposal_id": proposal["proposal_id"]})
    result = await apply.async_call(hass, arguments, context)
    result = result.data if hasattr(result, "data") else result
    assert result["status"] == "applied" and result["backup_available"] is True
    assert (await manager.read("automation", "morning"))["alias"] == "Direct update"
    restore = ConfigurationTool(manager, "restore")
    result = await restore.async_call(hass, arguments, context)
    result = result.data if hasattr(result, "data") else result
    assert result["status"] == "rolled_back" and await manager.read("automation", "morning") == before
    dashboard = await draft_dashboard(manager)
    denied = await apply.async_call(
        hass, llm.ToolInput(tool_name=apply.name, tool_args={"proposal_id": dashboard}), context
    )
    denied = denied.data if hasattr(denied, "data") else denied
    assert "error" in denied
    entry.options["automation_apply"] = False
    api = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert "configuration_apply" not in {tool.name for tool in api.tools}


async def test_real_chat_pipeline_reads_duplicate_proposes_and_applies_requested_change(
    environment, tmp_path, monkeypatch
):
    from homeassistant.components import conversation

    from custom_components.chatgpt_assist import conversation as agent
    from custom_components.chatgpt_assist.const import NAMESPACE

    hass, entry, manager, before, _ = environment
    entry.options["logs_access"] = False
    entry.runtime_data.session = None
    entry.runtime_data.access_token = AsyncMock(return_value="fake")
    second = {**before, "alias": "Second rule"}
    (tmp_path / "automations.yaml").write_text(yaml.safe_dump([before, second]))
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="Update the second rule",
        context=Context(user_id="admin"),
        conversation_id="test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "test")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, context, selected, prompt, extra):
        self.llm_api = await selected.async_get_api_instance(context)
        self.content[0] = conversation.SystemContent(content=prompt + self.llm_api.api_prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    count = 0

    async def response(*args):
        nonlocal count
        count += 1
        json.dumps(args[4])
        if count == 1:
            name, values = "configuration_read", {"kind": "automation", "target": "morning"}
        elif count == 2:
            name, values = (
                "configuration_propose",
                {
                    "kind": "automation",
                    "target": "morning",
                    "entry_index": 1,
                    "config_json": json.dumps({**second, "alias": "Updated second rule"}),
                },
            )
        elif count == 3:
            name, values = "configuration_apply", {"proposal_id": next(iter(manager.records))}
        else:
            return {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Applied the requested update."}],
                    }
                ]
            }
        return {
            "output": [
                {
                    "type": "function_call",
                    "namespace": NAMESPACE,
                    "name": name,
                    "call_id": f"call{count}",
                    "arguments": json.dumps(values),
                }
            ]
        }

    monkeypatch.setattr(agent, "response", response)
    result = await entity._async_handle_message(user, log)
    assert "Applied" in result.response.speech["plain"]["speech"]
    values = yaml.safe_load((tmp_path / "automations.yaml").read_text())
    assert values[0] == before and values[1]["alias"] == "Updated second rule"
    assert next(iter(manager.records.values()))["status"] == "applied"


async def test_native_config_entry_rename_retains_restore_authority_and_grants_new_id(environment):
    from homeassistant.config_entries import ConfigEntries, ConfigEntry

    from custom_components.chatgpt_assist.const import DOMAIN

    hass, old_entry, _, before, _ = environment
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Test",
        data={},
        options=dict(old_entry.options),
        source="user",
        unique_id="test",
        discovery_keys={},
        subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry
    manager = Administration(hass, entry)
    proposal = await manager.propose(
        "admin", "automation", "morning", json.dumps({**before, "id": "renamed_morning"})
    )
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin")
    assert {"morning", "renamed_morning"} <= set(entry.options["automation_ids"])
    assert (await manager.read("automation", "renamed_morning"))["alias"] == "Morning"
    await manager.apply_from_options(proposal["proposal_id"], reviewer_id="admin", rollback=True)
    assert await manager.read("automation", "morning") == before
