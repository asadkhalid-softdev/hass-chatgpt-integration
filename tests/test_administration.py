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
    assert reloads == [{"id": "morning"}]
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
    assert menu["menu_options"] == ["settings", "review"]
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
        ("automation", "morning", {**before, "id": "other"}),
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

    async def fail_after_write(record, config, expected):
        recovered = Administration(hass, entry)
        await recovered.load()
        assert recovered.records[proposal]["before"]["views"][0]["title"] == "Original"
        assert recovered.records[proposal]["status"] == "applying"
        await original(record, config, expected)
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


async def test_real_admin_conversation_proposes_without_applying(environment, monkeypatch):
    from homeassistant.components import conversation

    from custom_components.chatgpt_assist import conversation as agent
    from custom_components.chatgpt_assist.const import NAMESPACE

    hass, entry, manager, _, _ = environment
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
