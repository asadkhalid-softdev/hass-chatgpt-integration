"""Sidebar ownership, real Core context restoration, clear and request deduplication."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import conversation, frontend
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.helpers.chat_session import DATA_CHAT_SESSION

from custom_components.chatgpt_assist import panel
from custom_components.chatgpt_assist.compat import schema as vol
from custom_components.chatgpt_assist.const import DOMAIN
from custom_components.chatgpt_assist.conversation import inputs_from_log


@pytest.fixture
async def chat(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.helpers import device_registry

    hass.config_entries = ConfigEntries(hass, {})
    if hasattr(device_registry, "async_setup"):
        device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await er.async_load(hass)
    users = {
        key: SimpleNamespace(id=key, is_active=True, is_admin=(key == "admin"), system_generated=False)
        for key in ("admin", "one", "two")
    }
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(side_effect=lambda user_id: users.get(user_id)))
    entry = SimpleNamespace(
        entry_id="account", title="My ChatGPT", options={"model": "test", "control": True}
    )
    registry = er.async_get(hass)
    registered = registry.async_get_or_create("conversation", DOMAIN, entry.entry_id)
    hass.states.async_set(registered.entity_id, "ready")
    backend = panel.SidebarChat(hass)
    backend.entries[entry.entry_id] = entry
    hass.data[panel.PANEL_KEY] = backend
    calls = []

    async def converse(hass, **kwargs):
        user_input = conversation.ConversationInput(
            text=kwargs["text"],
            context=kwargs["context"],
            conversation_id=kwargs["conversation_id"],
            language=kwargs["language"],
            agent_id=kwargs["agent_id"],
            device_id=None,
            satellite_id=None,
        )
        with conversation.async_get_chat_log(
            hass, next_session(hass, kwargs["conversation_id"]), user_input
        ) as log:
            calls.append({"context": kwargs["context"], "inputs": inputs_from_log(log)})
            log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=kwargs["agent_id"],
                    content="A helpful answer.",
                    native={
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "A helpful answer."}],
                            }
                        ]
                    },
                )
            )
            return conversation.async_get_result_from_chat_log(user_input, log)

    monkeypatch.setattr(conversation, "async_converse", AsyncMock(side_effect=converse))
    yield hass, backend, entry, users, calls
    await hass.async_stop()


def next_session(hass, conversation_id):
    # Sidebar already owns the session; nested Core APIs reuse this same object.
    from homeassistant.helpers.chat_session import current_session

    return current_session.get()


async def send(backend, user="one", text="hello", request="request-1"):
    return await backend.send(user, "account", text, request, Context(user_id=user), "en")


async def test_send_and_reload_preserves_history_and_model_context(chat):
    hass, backend, entry, _, calls = chat
    first = await send(backend)
    assert [item["role"] for item in first["messages"]] == ["user", "assistant"]
    assert calls[0]["context"].user_id == "one"
    recovered = panel.SidebarChat(hass)
    await recovered.load()
    recovered.entries[entry.entry_id] = entry
    # Simulate Core expiring its in-memory conversation.
    sessions = hass.data[DATA_CHAT_SESSION]
    for session in sessions.values():
        session.async_cleanup()
    sessions.clear()
    await send(recovered, text="follow up", request="request-2")
    assert {"role": "user", "content": "hello"} in calls[-1]["inputs"]
    assert any(item.get("type") == "message" for item in calls[-1]["inputs"])
    assert len((await recovered.history("one", "account"))["messages"]) == 4


async def test_history_and_clear_are_user_scoped_and_reset_core_context(chat):
    hass, backend, _, _, calls = chat
    await send(backend)
    await send(backend, user="two", text="second user's private message")
    assert (await backend.history("one", "account"))["messages"][0]["content"] == "hello"
    assert (await backend.history("two", "account"))["messages"][0][
        "content"
    ] == "second user's private message"
    session_ids = set(hass.data[DATA_CHAT_SESSION])
    assert (await backend.clear("one", "account"))["messages"] == []
    assert len(hass.data[DATA_CHAT_SESSION]) == len(session_ids) - 1
    assert len((await backend.history("two", "account"))["messages"]) == 2
    await send(backend, text="after clearing", request="request-2")
    assert {"role": "user", "content": "hello"} not in calls[-1]["inputs"]
    recovered = panel.SidebarChat(hass)
    await recovered.load()
    recovered.entries = backend.entries
    assert len((await recovered.history("one", "account"))["messages"]) == 2


async def test_duplicate_send_does_not_repeat_inference_or_actions(chat):
    _, backend, _, _, calls = chat
    original = await send(backend)
    repeated = await send(backend)
    assert repeated == original
    assert len(calls) == 1


async def test_pending_requests_block_concurrent_send_and_clear(chat, monkeypatch):
    _, backend, _, _, _ = chat
    started, finish = asyncio.Event(), asyncio.Event()
    original = conversation.async_converse

    async def delayed(*args, **kwargs):
        started.set()
        await finish.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(conversation, "async_converse", delayed)
    task = asyncio.create_task(send(backend))
    await started.wait()
    try:
        assert (await backend.history("one", "account"))["busy"] is True
        with pytest.raises(panel.PanelError, match="already in progress"):
            await send(backend, request="request-2")
        with pytest.raises(panel.PanelError, match="current reply"):
            await backend.clear("one", "account")
    finally:
        finish.set()
        await task


async def test_inactive_users_admin_permissions_and_foreign_context_fail_closed(chat):
    _, backend, entry, users, _ = chat
    entry.options["administration"] = True
    assert await backend.agents("one") == []
    with pytest.raises(panel.PanelError, match="administrator"):
        await backend.history("one", "account")
    assert len(await backend.agents("admin")) == 1
    with pytest.raises(panel.PanelError, match="context"):
        await backend.send("admin", "account", "hello", "request", Context(user_id="one"))
    users["admin"].is_active = False
    assert await backend.agents("admin") == []


async def test_admin_history_stays_protected_after_role_and_option_changes(chat):
    _, backend, entry, users, _ = chat
    entry.options["administration"] = True
    await send(backend, user="admin")
    entry.options["administration"] = False
    users["admin"].is_admin = False
    with pytest.raises(panel.PanelError, match="administrator-only"):
        await backend.history("admin", "account")


async def test_errors_are_retained_and_interrupted_requests_are_not_replayed(chat, monkeypatch):
    _, backend, _, _, _ = chat
    monkeypatch.setattr(
        conversation, "async_converse", AsyncMock(side_effect=RuntimeError("secret provider details"))
    )
    result = await send(backend)
    assert result["messages"][-1]["status"] == "error"
    assert "secret" not in json.dumps(result)
    assert "check device state" in result["messages"][-1]["content"]
    assert await send(backend) == result
    assert conversation.async_converse.await_count == 1


async def test_archive_restores_function_history_without_executable_tool_inputs(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    log = conversation.ChatLog(hass, "session")
    log.async_add_user_content(conversation.UserContent(content="request"))
    log.async_add_assistant_content_without_tools(
        conversation.AssistantContent(
            agent_id="conversation.test",
            native={
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "action",
                        "name": "example",
                        "arguments": "{}",
                        "namespace": "home_assistant",
                    }
                ]
            },
        )
    )
    fields = (
        {"result": llm.ToolResult(data={"success": True})}
        if hasattr(llm, "ToolResult")
        else {"tool_result": {"success": True}}
    )
    log.async_add_assistant_content_without_tools(
        conversation.ToolResultContent(
            agent_id="conversation.test", tool_name="example", tool_call_id="action", **fields
        )
    )
    log.async_add_assistant_content_without_tools(
        conversation.AssistantContent(agent_id="conversation.test", content="Done")
    )
    saved = panel.archive(log)
    target = conversation.ChatLog(hass, "restored")
    panel.restore(target, saved, "conversation.test")
    assert inputs_from_log(target) == inputs_from_log(log)
    assert all(
        not item.tool_calls for item in target.content if isinstance(item, conversation.AssistantContent)
    )


async def test_retention_and_entry_removal(chat, monkeypatch):
    _, backend, _, _, _ = chat
    monkeypatch.setattr(panel, "MAX_MESSAGES", 4)
    for index in range(3):
        await send(backend, text=f"message-{index}", request=f"request-{index}")
    history = await backend.history("one", "account")
    assert len(history["messages"]) == 4
    assert history["messages"][0]["content"] == "message-1"
    await backend.remove_entry("account")
    assert not backend.records


async def test_websocket_uses_authenticated_identity_and_rejects_spoof_fields(chat):
    hass, backend, _, _, _ = chat
    connection = SimpleNamespace(
        user=SimpleNamespace(id="one"),
        context=lambda msg: Context(user_id="one"),
        send_result=lambda *args: None,
        send_error=lambda *args: None,
    )
    # Schema excludes all client-supplied user IDs, conversation IDs and agent IDs.
    with pytest.raises(vol.Invalid):
        panel.websocket_sidebar._ws_schema(
            {"id": 1, "type": f"{DOMAIN}/sidebar", "operation": "send", "user_id": "admin"}
        )
    spy = AsyncMock(wraps=backend.send)
    backend.send = spy
    panel.websocket_sidebar(
        hass,
        connection,
        {
            "id": 2,
            "type": f"{DOMAIN}/sidebar",
            "operation": "send",
            "entry_id": "account",
            "text": "hello",
            "request_id": "request",
        },
    )
    await hass.async_block_till_done()
    assert spy.call_args.args[0] == "one"
    assert spy.call_args.args[4].user_id == "one"


async def test_panel_registration_once_and_last_unload_removes_sidebar(chat):
    hass, _, entry, _, _ = chat
    # Fresh setup exercises actual panel registration without starting an HTTP listener.
    hass.data.pop(panel.PANEL_KEY)
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    from homeassistant.components import websocket_api

    hass.data[websocket_api.DOMAIN] = {}
    await panel.async_setup_panel(hass, entry)
    await panel.async_setup_panel(hass, entry)
    hass.http.async_register_static_paths.assert_awaited_once()
    from pathlib import Path

    paths = hass.http.async_register_static_paths.call_args.args[0]
    assert {item.url_path for item in paths} == {
        panel.ASSET_URL,
        "/chatgpt_assist_static/vendor/marked.js",
    }
    assert all(Path(item.path).is_file() for item in paths)
    assert frontend.DATA_PANELS in hass.data
    assert panel.PANEL_PATH in hass.data[frontend.DATA_PANELS]
    assert (
        hass.data[frontend.DATA_PANELS][panel.PANEL_PATH]
        .config["_panel_custom"]["module_url"]
        .endswith("?v=0.6.0")
    )
    panel.async_unload_panel(hass, entry.entry_id)
    assert panel.PANEL_PATH not in hass.data[frontend.DATA_PANELS]


async def test_real_conversation_handoff_uses_existing_agent_and_restarts_with_saved_context(
    chat, monkeypatch
):
    from homeassistant.components.conversation import agent_manager

    from custom_components.chatgpt_assist import conversation as agent_module
    from custom_components.chatgpt_assist.conversation import ChatGPTConversation

    hass, backend, entry, _, _ = chat
    entry.options["control"] = False
    entry.runtime_data = SimpleNamespace(session=None, access_token=AsyncMock(return_value="fake"))
    entity = ChatGPTConversation(entry)
    entity.hass = hass
    entity.entity_id = er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    # Real agent manager dispatch and ConversationEntity context; no platform bootstrap is needed.
    from homeassistant.components.conversation.const import DATA_COMPONENT

    hass.data[DATA_COMPONENT] = SimpleNamespace(
        get_entity=lambda identifier: entity if identifier == entity.entity_id else None
    )
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)
    monkeypatch.setattr(conversation, "async_converse", agent_manager.async_converse)

    async def provide(self, context, selected, prompt, extra):
        self.content[0] = conversation.SystemContent(content=prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    provider = AsyncMock(
        return_value={
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Real agent reply."}],
                }
            ]
        }
    )
    monkeypatch.setattr(agent_module, "response", provider)
    result = await send(backend)
    assert result["messages"][-1]["content"] == "Real agent reply."
    assert result["messages"][-1]["status"] == "complete"
    await send(backend, text="remember my first message", request="request-2")
    assert {"role": "user", "content": "hello"} in provider.call_args.args[3]


async def test_concurrent_panel_setup_registers_asset_and_route_once(chat):
    hass, _, entry, _, _ = chat
    hass.data.pop(panel.PANEL_KEY)
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    from homeassistant.components import websocket_api

    hass.data[websocket_api.DOMAIN] = {}
    await asyncio.gather(panel.async_setup_panel(hass, entry), panel.async_setup_panel(hass, entry))
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_log_enabled_admin_history_stays_private_without_configuration_access(chat):
    _, backend, entry, users, _ = chat
    assert not entry.options.get("administration")
    agents = await backend.agents("admin")
    assert agents[0]["logs_access"] is True
    assert (await backend.agents("one"))[0]["logs_access"] is False
    await send(backend, user="admin")
    users["admin"].is_admin = False
    with pytest.raises(panel.PanelError, match="administrator-only"):
        await backend.history("admin", entry.entry_id)
