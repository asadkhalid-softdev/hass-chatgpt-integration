"""Use the real HA entity and chat log with a constrained test LLM API."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm

from custom_components.chatgpt_assist import conversation as agent
from custom_components.chatgpt_assist.api import ModelError
from custom_components.chatgpt_assist.const import NAMESPACE


def function(name="set_light", call_id="call1", **kwargs):
    return {
        "type": "function_call",
        "namespace": NAMESPACE,
        "name": name,
        "call_id": call_id,
        "arguments": json.dumps({"entity_id": "light.kitchen"}),
        **kwargs,
    }


def message(text="Done"):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


@pytest.mark.parametrize(
    "output",
    [
        [function(name="arbitrary_service")],
        [function(namespace="evil")],
        [function(arguments="[]")],
        [function(arguments="invalid")],
        [function(), function()],
        [function(), function(call_id="call2")],
        [function(call_id=str(i)) for i in range(9)],
        [{"type": "computer_call"}],
    ],
)
def test_reject_malformed_unavailable_or_excessive_tools(output):
    with pytest.raises(ModelError):
        agent.parse_output(output, {"set_light"}, set(), 8)


def test_history_preserves_reasoning_namespace_and_results():
    output = [{"type": "reasoning", "encrypted_content": "opaque", "summary": []}, function()]
    log = SimpleNamespace(
        content=[
            conversation.SystemContent(content="instructions"),
            conversation.UserContent(content="turn on kitchen"),
            conversation.AssistantContent(agent_id="test", native={"output": output}),
            conversation.ToolResultContent(
                agent_id="test", tool_name="set_light", tool_call_id="call1", tool_result={"success": True}
            ),
        ]
    )
    inputs = agent.inputs_from_log(log)
    assert inputs[0]["role"] == "developer"
    assert inputs[2:4] == output
    assert inputs[-1]["type"] == "function_call_output"


async def test_real_chat_log_tools_and_multi_turn(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        options={"model": "account-model", "control": True},
        runtime_data=SimpleNamespace(session=None, access_token=AsyncMock(return_value="secret")),
    )
    entity = agent.ChatGPTConversation(entry)
    entity.hass = hass
    entity.entity_id = "conversation.chatgpt"
    user = conversation.ConversationInput(
        text="Turn on kitchen",
        context=Context(user_id="original-user"),
        conversation_id="test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    dispatched = []

    class SetLight(llm.Tool):
        name = "set_light"
        parameters = vol.Schema({vol.Required("entity_id"): str})

        async def async_call(self, hass, tool_input, llm_context):
            dispatched.append((tool_input.tool_args, llm_context.context.user_id))
            return {"success": True}

    class API(llm.API):
        async def async_get_api_instance(self, context):
            raise NotImplementedError

    api = llm.APIInstance(
        api=API(hass=hass, id="test", name="test"),
        api_prompt="",
        llm_context=user.as_llm_context("chatgpt_assist"),
        tools=[SetLight()],
    )
    log = conversation.ChatLog(hass, "test")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, context, selected, prompt, extra):
        assert selected == ["assist"]
        self.llm_api = api
        self.content[0] = conversation.SystemContent(content=prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    responses = AsyncMock(side_effect=[{"output": [function()]}, {"output": [message()]}])
    monkeypatch.setattr(agent, "response", responses)
    try:
        result = await entity._async_handle_message(user, log)
        assert result.response.speech["plain"]["speech"] == "Done"
        assert dispatched == [({"entity_id": "light.kitchen"}, "original-user")]
        assert responses.call_args.args[3][-1]["type"] == "function_call_output"
        assert responses.call_args.args[4][0]["type"] == "namespace"
    finally:
        await hass.async_stop()


async def test_control_off_cannot_dispatch(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        options={"model": "model", "control": False},
        runtime_data=SimpleNamespace(session=None, access_token=AsyncMock(return_value="secret")),
    )
    entity = agent.ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.chatgpt"
    user = conversation.ConversationInput(
        text="Turn on kitchen",
        context=Context(),
        conversation_id="test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "test")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, context, selected, prompt, extra):
        assert selected is None

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    monkeypatch.setattr(agent, "response", AsyncMock(return_value={"output": [function()]}))
    try:
        result = await entity._async_handle_message(user, log)
        assert result.response.response_type.value == "error"
        assert not any(isinstance(c, conversation.ToolResultContent) for c in log.content)
    finally:
        await hass.async_stop()
