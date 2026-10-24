"""Conversation entity with scoped HA tools and optional hosted internet search."""

from __future__ import annotations

import asyncio
import json
import logging

from homeassistant.components import conversation
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import intent, llm

from . import ChatGPTConfigEntry
from .administration import AdministrationError, ConfigurationAPI
from .api import ModelError, response
from .auth import AuthError, ConnectionError
from .compat import schema as vol
from .compat import schema_to_json
from .const import DEFAULT_PROMPT, DOMAIN, MAX_ROUNDS, MAX_TOOL_CALLS, NAMESPACE
from .web_search import SEARCH_PROMPT, cited_text

_LOGGER = logging.getLogger(__name__)


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


def parse_output(output: list[dict], allowed: set[str], seen: set[str], remaining: int, *, web_search=False):
    """Validate the entire batch before dispatching any call."""
    calls, text, batch, searches = [], [], set(), set()
    try:
        for item in output:
            kind = item["type"]
            if kind == "message":
                text.extend(cited_text(part) for part in item["content"] if part["type"] == "output_text")
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
            elif kind == "web_search_call":
                search_id = item.get("id")
                if (
                    not web_search
                    or item.get("status") != "completed"
                    or not isinstance(search_id, str)
                    or not search_id
                    or search_id in seen
                    or search_id in searches
                    or not isinstance(item.get("action"), dict)
                    or item["action"].get("type") not in {"search", "open_page", "find", "find_in_page"}
                ):
                    raise ValueError
                searches.add(search_id)
            elif kind != "reasoning":
                raise ValueError
        if len(calls) > min(remaining, 1) or len(calls) + len(searches) > remaining or batch & searches:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ModelError(
            "ChatGPT returned invalid or excessive tool calls. No actions from this response were run."
        ) from None
    seen.update(batch | searches)
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
            except (ConnectionError, ModelError) as err:
                _LOGGER.warning("ChatGPT Assist request failed: %s", err)
                # These integration errors contain only sanitized messages, never raw
                # provider response bodies, prompts, credentials or tool arguments.
                return self._error(
                    user_input,
                    chat_log,
                    str(err)
                    + (
                        " If this started after enabling internet search, disable Allow internet search in Configure or choose another model."
                        if self.entry.options.get("web_search")
                        else ""
                    )
                    + " If earlier actions ran, check device state before retrying.",
                )
            except TimeoutError:
                return self._error(
                    user_input,
                    chat_log,
                    "ChatGPT timed out [turn_timeout]. Check device state before retrying.",
                )

    async def _handle(self, user_input, chat_log):
        # Permission changes must not turn an administration log into a household chat.
        if not self.entry.options.get("administration") and any(
            isinstance(item, conversation.ToolResultContent) and item.tool_name.startswith("configuration_")
            for item in chat_log.content
        ):
            return self._error(
                user_input, chat_log, "Start a new conversation after disabling configuration administration."
            )
        if self.entry.options.get("administration"):
            try:
                await self.entry.runtime_data.administration.authorize(user_input.context.user_id)
            except AdministrationError as err:
                return self._error(user_input, chat_log, str(err))
        # Do not resend historical readings after access or entity permissions are revoked.
        if self.entry.options.get("history_access") or any(
            isinstance(item, conversation.ToolResultContent) and item.tool_name.startswith("history_")
            for item in chat_log.content
        ):
            from .history import HistoryAccess, HistoryError

            access = HistoryAccess(self.hass, self.entry)
            try:
                await access.authorize(user_input.context.user_id)
                for item in chat_log.content:
                    if isinstance(item, conversation.ToolResultContent) and item.tool_name.startswith(
                        "history_"
                    ):
                        data = item.result.data if hasattr(item, "result") else item.tool_result
                        if isinstance(data, dict):
                            await access.authorize(user_input.context.user_id, data.get("entity_ids", []))
            except HistoryError as err:
                return self._error(user_input, chat_log, str(err) + " Clear message history before retrying.")
        from .logs import LogsAccess, LogsError

        logs_access = LogsAccess(self.hass, self.entry)
        logs_available = self.entry.options.get("logs_access", True) and await logs_access.is_admin(
            user_input.context.user_id
        )
        if any(
            isinstance(item, conversation.ToolResultContent) and item.tool_name.startswith("logs_")
            for item in chat_log.content
        ):
            try:
                await logs_access.authorize(user_input.context.user_id)
            except LogsError as err:
                return self._error(user_input, chat_log, str(err) + " Clear message history before retrying.")
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            (
                ConfigurationAPI(self.hass, self.entry)
                if self.entry.options.get("administration")
                or self.entry.options.get("history_access")
                or logs_available
                else [llm.LLM_API_ASSIST]
                if self.entry.options.get("control")
                else None
            ),
            DEFAULT_PROMPT
            + (
                "\n" + SEARCH_PROMPT
                if self.entry.options.get("web_search", False)
                else "\nInternet search is disabled. Do not claim to have performed a new internet lookup."
            ),
            user_input.extra_system_prompt,
        )
        tools, allowed = [], set()
        if chat_log.llm_api:
            allowed = {tool.name for tool in chat_log.llm_api.tools}
            tools = [
                {
                    "type": "namespace",
                    "name": NAMESPACE,
                    "description": "Home Assistant device tools, sensor history, administrator logs and configuration operations.",
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
        search_enabled = self.entry.options.get("web_search", False)
        if search_enabled:
            tools.append({"type": "web_search"})
        reasoning_effort = self.entry.options.get("reasoning_effort", "default")
        reasoning_options = {} if reasoning_effort == "default" else {"reasoning_effort": reasoning_effort}
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
                    **reasoning_options,
                )
            )["output"]
            text, calls = parse_output(
                output, allowed, seen, MAX_TOOL_CALLS - len(seen), web_search=search_enabled
            )
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
