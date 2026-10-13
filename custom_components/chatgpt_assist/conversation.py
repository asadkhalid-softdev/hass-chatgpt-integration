"""Conversation entity using only HA's exposed-entity Assist API."""

from __future__ import annotations

import asyncio
import json

from homeassistant.components import conversation
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import intent, llm

from . import ChatGPTConfigEntry
from .api import ModelError, response
from .auth import AuthError, ConnectionError
from .compat import schema as vol
from .compat import schema_to_json
from .const import DEFAULT_PROMPT, DOMAIN, MAX_ROUNDS, MAX_TOOL_CALLS, NAMESPACE


async def async_setup_entry(hass, entry: ChatGPTConfigEntry, async_add_entities):
    """Create one selectable conversation assistant per account registration."""
    async_add_entities([ChatGPTConversation(entry)])


def inputs_from_log(chat_log) -> list[dict]:
    """Preserve full Responses output (including encrypted reasoning) locally."""
    result = []
    for item in chat_log.content:
        if isinstance(item, conversation.ToolResultContent):
            if hasattr(item, "result"):
                data = item.result.data
                if item.result.error:
                    data = {"error": True, "data": data}
            else:
                data = item.tool_result
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": item.tool_call_id,
                    "output": json.dumps(data),
                }
            )
        elif isinstance(item, conversation.AssistantContent) and isinstance(item.native, dict):
            result.extend(item.native["output"])
        elif item.content:
            result.append(
                {"role": "developer" if item.role == "system" else item.role, "content": item.content}
            )
    return result


def parse_output(output: list[dict], allowed: set[str], seen: set[str], remaining: int):
    """Validate the entire batch before dispatching any call."""
    calls, text, batch = [], [], set()
    try:
        for item in output:
            kind = item["type"]
            if kind == "message":
                text.extend(part["text"] for part in item["content"] if part["type"] == "output_text")
            elif kind == "function_call":
                name, call_id = item["name"], item["call_id"]
                if (
                    item.get("namespace") != NAMESPACE
                    or name not in allowed
                    or not isinstance(call_id, str)
                    or not call_id
                    or call_id in seen
                    or call_id in batch
                ):
                    raise ValueError
                args = json.loads(item["arguments"])
                if not isinstance(args, dict):
                    raise ValueError
                calls.append(llm.ToolInput(tool_name=name, tool_args=args, id=call_id))
                batch.add(call_id)
            elif kind != "reasoning":
                raise ValueError
        if len(calls) > min(remaining, 1):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ModelError(
            "ChatGPT returned invalid or excessive tool calls. No actions from this response were run."
        ) from None
    seen.update(batch)
    return "\n".join(text), calls


class ChatGPTConversation(conversation.ConversationEntity):
    """Account-backed text agent compatible with Assist pipelines."""

    _attr_has_entity_name = True
    _attr_name = "ChatGPT Assist"

    def __init__(self, entry: ChatGPTConfigEntry):
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._lock = asyncio.Lock()
        if entry.options.get("control", False):
            self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self):
        return "*"

    async def _async_handle_message(self, user_input, chat_log):
        # Serialize turns for this account to avoid simultaneous household actions.
        async with self._lock:
            try:
                async with asyncio.timeout(180):
                    return await self._handle(user_input, chat_log)
            except conversation.ConverseError as err:
                return err.as_conversation_result()
            except AuthError:
                self.entry.async_start_reauth(self.hass)
                return self._error(
                    user_input, chat_log, "ChatGPT authorization failed. Reauthenticate ChatGPT Assist."
                )
            except ConfigEntryAuthFailed:
                return self._error(
                    user_input, chat_log, "ChatGPT session expired. Reauthenticate ChatGPT Assist."
                )
            except (ConnectionError, ModelError, TimeoutError):
                return self._error(
                    user_input,
                    chat_log,
                    "ChatGPT could not complete this request. Some requested actions may already have completed; "
                    "check device state before retrying. Check ChatGPT plan access and usage, or start a new conversation.",
                )

    async def _handle(self, user_input, chat_log):
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            [llm.LLM_API_ASSIST] if self.entry.options.get("control") else None,
            DEFAULT_PROMPT,
            user_input.extra_system_prompt,
        )
        tools, allowed = [], set()
        if chat_log.llm_api:
            allowed = {tool.name for tool in chat_log.llm_api.tools}
            tools = [
                {
                    "type": "namespace",
                    "name": NAMESPACE,
                    "description": "Home Assistant exposed-entity state and control tools.",
                    "tools": [
                        {
                            "type": "function",
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "strict": False,
                            "parameters": schema_to_json(
                                tool.parameters, custom_serializer=chat_log.llm_api.custom_serializer
                            ),
                        }
                        for tool in chat_log.llm_api.tools
                    ],
                }
            ]
        seen: set[str] = set()
        for _ in range(MAX_ROUNDS):
            account = self.entry.runtime_data
            output = (
                await response(
                    account.session,
                    await account.access_token(),
                    self.entry.options["model"],
                    inputs_from_log(chat_log),
                    tools,
                )
            )["output"]
            text, calls = parse_output(output, allowed, seen, MAX_TOOL_CALLS - len(seen))
            # Validate schemas before any call in the batch executes.
            if calls:
                try:
                    schemas = {tool.name: tool.parameters for tool in chat_log.llm_api.tools}
                    for call in calls:
                        call.tool_args = schemas[call.tool_name](call.tool_args)
                except vol.Invalid:
                    raise ModelError("ChatGPT returned invalid tool arguments.") from None
            content = conversation.AssistantContent(
                agent_id=self.entity_id,
                content=text or None,
                tool_calls=calls or None,
                native={"output": output},
            )
            if not calls:
                if not text:
                    raise ModelError("ChatGPT returned no answer.")
                chat_log.async_add_assistant_content_without_tools(content)
                return conversation.async_get_result_from_chat_log(user_input, chat_log)
            # HA attaches the user's original Context and enforces Assist exposure/intents.
            async for _result in chat_log.async_add_assistant_content(content):
                pass
        raise ModelError("ChatGPT exceeded the action limit.")

    @staticmethod
    def _error(user_input, chat_log, message):
        result = intent.IntentResponse(language=user_input.language)
        result.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, message)
        return conversation.ConversationResult(response=result, conversation_id=chat_log.conversation_id)
