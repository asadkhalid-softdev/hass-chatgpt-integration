"""Authenticated sidebar chat with private, per-user history and clear semantics."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import time
from pathlib import Path

from homeassistant.components import conversation, frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.helpers.storage import Store

from .compat import schema as vol
from .const import DOMAIN

PANEL_KEY = f"{DOMAIN}.panel"
PANEL_PATH = "chatgpt-assist"
ASSET_URL = "/chatgpt_assist_static/panel.js"
MAX_MESSAGES = 60
MAX_HISTORY_BYTES = 128_000
MAX_CONTEXT_BYTES = 160_000


class PanelError(HomeAssistantError):
    """Safe sidebar operation error."""


def archive(log):
    """Persist data, never pending executable HA ToolInput objects or system prompts."""
    result = []
    for item in log.content:
        if isinstance(item, conversation.UserContent):
            result.append({"role": "user", "content": item.content})
        elif isinstance(item, conversation.AssistantContent):
            result.append({"role": "assistant", "content": item.content, "native": item.native})
        elif isinstance(item, conversation.ToolResultContent):
            data = item.result.data if hasattr(item, "result") else item.tool_result
            result.append(
                {
                    "role": "tool_result",
                    "tool_name": item.tool_name,
                    "tool_call_id": item.tool_call_id,
                    "data": data,
                    "error": item.result.error if hasattr(item, "result") else False,
                }
            )
    # Strip dict-subclass attributes (for example IntentResponseDict.original),
    # retaining only the JSON data that can be sent back to the provider.
    result = json.loads(json.dumps(result))
    # Trim whole turns, keeping function calls and their outputs together.
    while result and (len(result) > 240 or len(json.dumps(result).encode()) > MAX_CONTEXT_BYTES):
        next_turn = next((i for i, item in enumerate(result[1:], 1) if item["role"] == "user"), len(result))
        result = result[next_turn:]
    return result


def restore(log, saved, agent_id):
    """Restore only backend-owned records into a fresh Core chat log, without execution."""
    for item in saved:
        if item["role"] == "user":
            log.async_add_user_content(conversation.UserContent(content=item["content"]))
        elif item["role"] == "assistant":
            log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=agent_id, content=item["content"], native=item.get("native")
                )
            )
        elif item["role"] == "tool_result":
            fields = (
                {"result": llm.ToolResult(data=item["data"], error=item.get("error", False))}
                if hasattr(llm, "ToolResult")
                else {"tool_result": item["data"]}
            )
            log.async_add_assistant_content_without_tools(
                conversation.ToolResultContent(
                    agent_id=agent_id,
                    tool_name=item["tool_name"],
                    tool_call_id=item["tool_call_id"],
                    **fields,
                )
            )


class SidebarChat:
    """One backend; callers cannot supply another user, agent or conversation context."""

    def __init__(self, hass):
        self.hass = hass
        self.entries = {}
        self.records = {}
        self.locks = {}
        self.save_lock = asyncio.Lock()
        self.store = Store(hass, 1, f"{DOMAIN}.sidebar_history", private=True)

    async def load(self):
        self.records = await self.store.async_load() or {}

    async def save(self):
        async with self.save_lock:
            await self.store.async_save(copy.deepcopy(self.records))

    async def authorize(self, user_id, entry_id):
        user = await self.hass.auth.async_get_user(user_id)
        entry = self.entries.get(entry_id)
        if not user or not user.is_active or user.system_generated:
            raise PanelError("Sign in with an active Home Assistant user account.")
        if entry is None:
            raise PanelError("This assistant is unavailable. Refresh the assistant list.")
        if entry.options.get("administration") and not user.is_admin:
            raise PanelError(
                "This assistant requires an administrator because configuration access is enabled."
            )
        agent_id = er.async_get(self.hass).async_get_entity_id("conversation", DOMAIN, entry_id)
        if not agent_id or self.hass.states.get(agent_id) is None:
            raise PanelError("This assistant is still loading or unavailable. Try again shortly.")
        key = hashlib.sha256(f"{user_id}:{entry_id}".encode()).hexdigest()
        record = self.records.get(key)
        if record and record.get("administrative") and not user.is_admin:
            raise PanelError(
                "This history contains administrator-only data and is unavailable to this account."
            )
        return key, entry, agent_id

    async def agents(self, user_id):
        user = await self.hass.auth.async_get_user(user_id)
        result = []
        for entry_id, entry in list(self.entries.items()):
            try:
                await self.authorize(user_id, entry_id)
            except PanelError:
                continue
            result.append(
                {
                    "entry_id": entry_id,
                    "title": entry.title,
                    "model": entry.options.get("model", ""),
                    "web_search": entry.options.get("web_search", False),
                    "administration": entry.options.get("administration", False),
                    "logs_access": bool(user and user.is_admin and entry.options.get("logs_access", True)),
                    "direct_automation_updates": bool(
                        entry.options.get("administration") and entry.options.get("automation_apply", True)
                    ),
                }
            )

        def recent(item):
            key = hashlib.sha256(f"{user_id}:{item['entry_id']}".encode()).hexdigest()
            messages = self.records.get(key, {}).get("messages", [])
            return messages[-1]["time"] if messages else 0

        result.sort(key=recent, reverse=True)
        return result

    def record(self, key, user_id, entry_id):
        if key not in self.records:
            if len(self.records) >= 100:
                raise PanelError(
                    "Sidebar history storage is full. Clear an existing chat or remove an unused assistant."
                )
            self.records[key] = {
                "owner": user_id,
                "entry_id": entry_id,
                "session": "chatgpt-panel-" + secrets.token_hex(24),
                "messages": [],
                "context": [],
                "administrative": False,
            }
        return self.records[key]

    def public(self, key):
        record = self.records.get(key, {"messages": []})
        busy = self.locks.get(key, asyncio.Lock()).locked()
        messages = copy.deepcopy(record["messages"])
        if not busy:
            for item in messages:
                if item.get("status") == "pending":
                    item.update(
                        status="error",
                        content="The reply was interrupted. Some actions may have completed; check device state before retrying.",
                    )
        return {"messages": messages, "busy": busy}

    async def history(self, user_id, entry_id):
        key, _, _ = await self.authorize(user_id, entry_id)
        return self.public(key)

    async def clear(self, user_id, entry_id):
        key, _, _ = await self.authorize(user_id, entry_id)
        lock = self.locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            raise PanelError("Wait for the current reply before clearing history.")
        async with lock:
            record = self.records.pop(key, None)
            if record:
                # Remove Core's active session/log as well as the persisted transcript.
                from homeassistant.helpers.chat_session import DATA_CHAT_SESSION

                sessions = self.hass.data.get(DATA_CHAT_SESSION, {})
                if session := sessions.pop(record["session"], None):
                    session.async_cleanup()
            await self.save()
        return self.public(key)

    async def send(self, user_id, entry_id, text, request_id, context, language=None):
        if not text.strip() or len(text) > 4000 or not request_id or len(request_id) > 128:
            raise PanelError("Enter a message of up to 4,000 characters.")
        if context.user_id != user_id:
            raise PanelError("The authenticated request context is invalid.")
        key, entry, agent_id = await self.authorize(user_id, entry_id)
        lock = self.locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            raise PanelError("A reply is already in progress for this chat. Wait before sending again.")
        async with lock:
            record = self.record(key, user_id, entry_id)
            if any(item.get("request_id") == request_id for item in record["messages"]):
                return {**self.public(key), "busy": False}
            from .logs import LogsAccess

            record["administrative"] |= bool(entry.options.get("administration")) or (
                entry.options.get("logs_access", True)
                and await LogsAccess(self.hass, entry).is_admin(user_id)
            )
            record["messages"].append(
                {"role": "user", "content": text.strip(), "time": time.time(), "request_id": request_id}
            )
            reply = {
                "role": "assistant",
                "content": "",
                "status": "pending",
                "time": time.time(),
                "request_id": request_id,
            }
            record["messages"].append(reply)
            await self.save()  # Record delivery before a potentially irreversible action.
            with (
                async_get_chat_session(self.hass, record["session"]) as session,
                conversation.async_get_chat_log(self.hass, session) as log,
            ):
                # Use the same scoped session after expiry/restart and restore data only.
                if len(log.content) == 1 and record["context"]:
                    restore(log, record["context"], agent_id)
                try:
                    result = await conversation.async_converse(
                        self.hass,
                        text=text.strip(),
                        conversation_id=session.conversation_id,
                        agent_id=agent_id,
                        context=context,
                        language=language or self.hass.config.language,
                    )
                    speech = result.response.speech.get("plain", {}).get("speech", "")
                    reply.update(
                        content=speech[:16000],
                        status="error" if result.response.response_type.value == "error" else "complete",
                    )
                    if len(speech) > 16000:
                        reply["content"] += (
                            "\n\nThe response was shortened for this chat. Ask for a smaller section."
                        )
                    if reply["status"] == "error":
                        log.async_add_assistant_content_without_tools(
                            conversation.AssistantContent(agent_id=agent_id, content=reply["content"])
                        )
                except Exception:
                    reply.update(
                        status="error",
                        content="The assistant could not complete this message. Some actions may have completed; check device state before retrying.",
                    )
                    log.async_add_assistant_content_without_tools(
                        conversation.AssistantContent(agent_id=agent_id, content=reply["content"])
                    )
                record["context"] = archive(log)
                # Bound live context too, so sidebar conversations do not accumulate forever.
                log.content = log.content[:1]
                restore(log, record["context"], agent_id)
            while (
                len(record["messages"]) > MAX_MESSAGES
                or len(json.dumps(record["messages"]).encode()) > MAX_HISTORY_BYTES
            ):
                del record["messages"][:2]
            await self.save()
            await self.authorize(user_id, entry_id)
            return {**self.public(key), "busy": False}

    async def remove_entry(self, entry_id):
        self.records = {key: value for key, value in self.records.items() if value["entry_id"] != entry_id}
        await self.save()

    async def send_external(self, user_id, entry_id, text, request_id, context, language, prompt, valid):
        """An Alexa-only turn: fresh inference, transcript-only append, no chat-context mutation."""
        key, entry, agent_id = await self.authorize(user_id, entry_id)
        if context.user_id != user_id:
            raise PanelError("Invalid voice request context.")
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self.authorize(user_id, entry_id)
            if not valid():
                raise PanelError("Alexa access was revoked.")
            record = self.record(key, user_id, entry_id)
            from .logs import LogsAccess

            record["administrative"] |= bool(entry.options.get("administration")) or (
                entry.options.get("logs_access", True)
                and await LogsAccess(self.hass, entry).is_admin(user_id)
            )
            record["messages"].append(
                {
                    "role": "user",
                    "content": text,
                    "time": time.time(),
                    "request_id": request_id,
                    "source": "alexa",
                }
            )
            reply = {
                "role": "assistant",
                "content": "",
                "status": "pending",
                "time": time.time(),
                "request_id": request_id,
                "source": "alexa",
                "delivery": "pending",
            }
            record["messages"].append(reply)
            await self.save()
            try:
                # Explicitly create a NEW Core session: never restore sidebar context or another Echo turn.
                with async_get_chat_session(self.hass) as voice_session:
                    result = await conversation.async_converse(
                        self.hass,
                        text=text,
                        conversation_id=voice_session.conversation_id,
                        agent_id=agent_id,
                        context=context,
                        language=language,
                        extra_system_prompt=prompt,
                    )
                speech = result.response.speech.get("plain", {}).get("speech", "")
                reply.update(
                    content=speech[:16000],
                    status="error" if result.response.response_type.value == "error" else "complete",
                )
            except asyncio.CancelledError:
                reply.update(
                    status="error", content="Voice request interrupted. Check device state before retrying."
                )
                raise
            except Exception:
                reply.update(
                    status="error",
                    content="The voice request failed. Some actions may have completed; check device state before retrying.",
                )
            finally:
                while (
                    len(record["messages"]) > MAX_MESSAGES
                    or len(json.dumps(record["messages"]).encode()) > MAX_HISTORY_BYTES
                ):
                    del record["messages"][:2]
                await self.save()
            await self.authorize(user_id, entry_id)
            return reply["content"] or "The assistant returned no spoken answer."

    async def external_delivery(self, user_id, entry_id, request_id, status):
        """Update delivery metadata without adding messages or modifying inference context."""
        key = hashlib.sha256(f"{user_id}:{entry_id}".encode()).hexdigest()
        async with self.locks.setdefault(key, asyncio.Lock()):
            for item in self.records.get(key, {}).get("messages", []):
                if item.get("request_id") == request_id and item.get("role") == "assistant":
                    item["delivery"] = status
            await self.save()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/sidebar",
        vol.Required("operation"): vol.In(["agents", "history", "send", "clear"]),
        vol.Optional("entry_id"): str,
        vol.Optional("text"): str,
        vol.Optional("request_id"): str,
        vol.Optional("language"): str,
    }
)
@websocket_api.async_response
async def websocket_sidebar(hass, connection, msg):
    """Use the WebSocket's authenticated user and Context, never client identity fields."""
    try:
        backend = hass.data[PANEL_KEY]
        operation, user_id = msg["operation"], connection.user.id
        if operation == "agents":
            result = {"agents": await backend.agents(user_id)}
        elif operation == "history":
            result = await backend.history(user_id, msg.get("entry_id"))
        elif operation == "clear":
            result = await backend.clear(user_id, msg.get("entry_id"))
        else:
            result = await backend.send(
                user_id,
                msg.get("entry_id"),
                msg.get("text", ""),
                msg.get("request_id", ""),
                connection.context(msg),
                msg.get("language"),
            )
        connection.send_result(msg["id"], result)
    except PanelError as err:
        connection.send_error(msg["id"], "chat_unavailable", str(err))
    except Exception:
        connection.send_error(
            msg["id"],
            "chat_failed",
            "The chat could not be completed or saved. Some actions may have completed; check device state before retrying.",
        )


async def async_setup_panel(hass: HomeAssistant, entry):
    """Register one locally served panel for all configured accounts."""
    async with hass.data.setdefault(f"{DOMAIN}.panel_setup_lock", asyncio.Lock()):
        existing = hass.data.get(frontend.DATA_PANELS, {}).get(PANEL_PATH)
        if (
            existing
            and (existing.config or {}).get("_panel_custom", {}).get("name") != "chatgpt-assist-panel"
        ):
            raise PanelError("The /chatgpt-assist sidebar path is already used by another panel.")
        if PANEL_KEY not in hass.data:
            backend = SidebarChat(hass)
            await backend.load()
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(ASSET_URL, str(Path(__file__).parent / "frontend" / "panel.js"), False),
                    StaticPathConfig(
                        "/chatgpt_assist_static/vendor/marked.js",
                        str(Path(__file__).parent / "frontend" / "vendor" / "marked.js"),
                        False,
                    ),
                ]
            )
            websocket_api.async_register_command(hass, websocket_sidebar)
            hass.data[PANEL_KEY] = backend
        backend = hass.data[PANEL_KEY]
        backend.entries[entry.entry_id] = entry
        if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_PATH,
                webcomponent_name="chatgpt-assist-panel",
                sidebar_title="ChatGPT Assist",
                sidebar_icon="mdi:chat-outline",
                module_url=ASSET_URL + "?v=0.7.0",
                require_admin=False,
            )


def async_unload_panel(hass, entry_id):
    if backend := hass.data.get(PANEL_KEY):
        backend.entries.pop(entry_id, None)
        if not backend.entries:
            frontend.async_remove_panel(hass, PANEL_PATH)
