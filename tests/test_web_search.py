"""Hosted search opt-in, safe citations, history and separation from HA actions."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm

from custom_components.chatgpt_assist import conversation as agent
from custom_components.chatgpt_assist.api import ModelError
from custom_components.chatgpt_assist.compat import schema as vol
from custom_components.chatgpt_assist.const import MAX_TOOL_CALLS, NAMESPACE
from custom_components.chatgpt_assist.web_search import citation_url, cited_text


def search(**changes):
    return {
        "type": "web_search_call",
        "id": "ws_1",
        "status": "completed",
        "action": {"type": "search", "query": "public topic"},
        **changes,
    }


def cited_message(text="Current result.", url="https://example.com/news"):
    return {
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": [
                    {
                        "type": "url_citation",
                        "start_index": 0,
                        "end_index": len(text),
                        "url": url,
                        "title": "Source title",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,payload",
        "file:///config/secrets.yaml",
        "https://user:secret@example.com/page",
        "https://example.com/\nattack",
        "http://localhost/page",
        "http://127.0.0.1/page",
        "http://192.168.1.3/",
        "http://[::1]/",
        "http://127.1/",
        "http://%31%32%37.0.0.1/",
        "http://hass.local/page",
        "https://example.com\\@evil.com/",
        "https://example.com:bad/",
        "https://example.com>evil/",
        "https://example.com<evil/",
        "http://localhost./",
        None,
    ],
)
def test_citation_links_reject_unsafe_urls(url):
    assert citation_url(url) is None


def test_citations_visible_clickable_and_url_markup_escaped():
    part = cited_message(url="https://example.com/news?q=<script>(x)")["content"][0]
    rendered = cited_text(part)
    assert "[1](<https://example.com/news?q=%3Cscript%3E%28x%29>)" in rendered
    assert "<script>" not in rendered
    assert part["text"] == "Current result."  # Native history is untouched.


def test_citation_positions_deduplication_and_opaque_marker_conversion():
    original = "Fact.citeturn0search0 More text."
    end = original.index(" More")
    part = {
        "text": original,
        "annotations": [
            {"type": "url_citation", "start_index": 5, "end_index": end, "url": "https://example.com"}
        ],
    }
    part["annotations"].append(dict(part["annotations"][0]))
    assert cited_text(part) == "Fact. [1](<https://example.com>) More text."
    part["annotations"][0]["end_index"] = 99999
    assert "[1](<https://example.com>)" in cited_text(part)


def test_bad_or_excessive_citations_prevent_action_dispatch():
    for annotations in ({}, [dict(type="url_citation")] * 65):
        part = {"type": "output_text", "text": "Fact", "annotations": annotations}
        with pytest.raises(ModelError):
            agent.parse_output([{"type": "message", "content": [part]}], set(), set(), 8, web_search=True)


@pytest.mark.parametrize(
    "item",
    [
        search(status="failed"),
        search(status="in_progress"),
        search(id=""),
        search(action={"type": "computer_use"}),
        search(action=None),
    ],
)
def test_invalid_search_output_is_rejected(item):
    with pytest.raises(ModelError):
        agent.parse_output([item, cited_message()], set(), set(), MAX_TOOL_CALLS, web_search=True)


def test_search_requires_opt_in_and_counts_toward_completed_output_budget():
    with pytest.raises(ModelError):
        agent.parse_output([search(), cited_message()], set(), set(), 8)
    seen = set()
    text, calls = agent.parse_output([search(), cited_message()], set(), seen, 8, web_search=True)
    assert "[1](<https://example.com/news>)" in text
    assert calls == [] and seen == {"ws_1"}
    with pytest.raises(ModelError):
        agent.parse_output([search()], set(), seen, 7, web_search=True)
    with pytest.raises(ModelError):
        agent.parse_output([search(), search(id="ws_2")], set(), set(), 1, web_search=True)


@pytest.mark.parametrize("enabled", [False, True])
async def test_real_chat_log_hosted_search_is_opt_in_without_device_control(tmp_path, monkeypatch, enabled):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        options={"model": "test-model", "control": False, "web_search": enabled},
        runtime_data=SimpleNamespace(session=None, access_token=AsyncMock(return_value="fake-token")),
    )
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="Look up a public topic",
        context=Context(),
        conversation_id="search",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "search")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, context, selected, prompt, extra):
        assert selected is None
        self.content[0] = conversation.SystemContent(content=prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    output = [search(), cited_message()] if enabled else [cited_message()]
    provider = AsyncMock(return_value={"output": output})
    monkeypatch.setattr(agent, "response", provider)
    try:
        result = await entity._async_handle_message(user, log)
        assert result.response.response_type.value != "error"
        assert provider.call_args.args[4] == ([{"type": "web_search"}] if enabled else [])
        assert not any(isinstance(item, conversation.ToolResultContent) for item in log.content)
        assert log.content[-1].native["output"] == output
        if enabled:
            assert agent.inputs_from_log(log)[-2:] == output
            assert "[1](<https://example.com/news>)" in result.response.speech["plain"]["speech"]
    finally:
        await hass.async_stop()


async def test_search_with_ha_tool_uses_user_context_and_preserves_search_history(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        options={"model": "test", "control": True, "web_search": True},
        runtime_data=SimpleNamespace(session=None, access_token=AsyncMock(return_value="fake-token")),
    )
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="Search a public topic and turn on kitchen light",
        context=Context(user_id="original"),
        conversation_id="combined",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    dispatched = []

    class SetLight(llm.Tool):
        name = "set_light"
        integration = "chatgpt_assist"
        parameters = vol.Schema({vol.Required("entity_id"): str})

        async def async_call(self, hass, tool_input, context):
            dispatched.append(context.context.user_id)
            return llm.ToolResult(data={"success": True}) if hasattr(llm, "ToolResult") else {"success": True}

    async def provide(self, context, selected, prompt, extra):
        self.llm_api = llm.APIInstance(
            api=SimpleNamespace(hass=hass),
            llm_context=context,
            api_prompt="",
            tools=[SetLight()],
            custom_serializer=llm.selector_serializer,
        )
        self.content[0] = conversation.SystemContent(content=prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    function = {
        "type": "function_call",
        "name": "set_light",
        "namespace": NAMESPACE,
        "call_id": "ha_call",
        "arguments": json.dumps({"entity_id": "light.kitchen"}),
    }
    provider = AsyncMock(side_effect=[{"output": [search(), function]}, {"output": [cited_message()]}])
    monkeypatch.setattr(agent, "response", provider)
    log = conversation.ChatLog(hass, "combined")
    log.async_add_user_content(conversation.UserContent(content=user.text))
    try:
        result = await entity._async_handle_message(user, log)
        assert result.response.response_type.value != "error"
        assert dispatched == ["original"]
        tools = provider.call_args.args[4]
        assert [tool["type"] for tool in tools] == ["namespace", "web_search"]
        inputs = provider.call_args.args[3]
        assert search() in inputs and function in inputs
        assert inputs[-1]["type"] == "function_call_output" and inputs[-1]["call_id"] == "ha_call"
    finally:
        await hass.async_stop()


async def test_search_option_default_off_and_saved_in_native_settings(tmp_path, monkeypatch):
    from homeassistant.config_entries import ConfigEntries

    from custom_components.chatgpt_assist import config_flow as flow_module
    from custom_components.chatgpt_assist.administration import Administration

    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    entry = SimpleNamespace(entry_id="test", options={"model": "test", "control": False})
    entry.runtime_data = SimpleNamespace(
        access_token=AsyncMock(return_value="fake"), administration=Administration(hass, entry)
    )
    monkeypatch.setattr(
        flow_module, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    monkeypatch.setattr(flow_module, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(flow_module.ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    flow = flow_module.ChatGPTOptionsFlow()
    flow.hass = hass
    try:
        form = await flow.async_step_settings()
        options = form["data_schema"]({"automations": {}, "dashboards": {}, "sensors": {}})
        assert options["web_search"] is False
        options["web_search"] = True
        saved = await flow.async_step_settings(options)
        assert saved["data"]["web_search"] is True
        assert saved["data"]["control"] is False
        assert saved["data"]["administration"] is False
        assert saved["data"]["automation_ids"] == []
    finally:
        await hass.async_stop()


async def test_search_access_error_is_actionable_without_reauthentication_or_retry(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    reauth = AsyncMock()
    entry = SimpleNamespace(
        entry_id="test",
        options={"model": "test", "web_search": True},
        async_start_reauth=reauth,
        runtime_data=SimpleNamespace(session=None, access_token=AsyncMock(return_value="fake")),
    )
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="search",
        context=Context(),
        conversation_id="failure",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "failure")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, *args):
        pass

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    provider = AsyncMock(
        side_effect=ModelError("Search is unsupported [subscription_sharing_unsupported_capability].")
    )
    monkeypatch.setattr(agent, "response", provider)
    try:
        result = await entity._async_handle_message(user, log)
        assert result.response.response_type.value == "error"
        assert "disable Allow internet search" in result.response.speech["plain"]["speech"]
        assert "check device state" in result.response.speech["plain"]["speech"]
        assert provider.await_count == 1
        reauth.assert_not_called()
    finally:
        await hass.async_stop()
