"""Bounded Responses transport; failed streams never dispatch actions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from .auth import AuthError, ConnectionError, request_json
from .const import API_URL, MAX_INPUT_BYTES, MAX_RESPONSE_BYTES


class ModelError(Exception):
    """Safe model/protocol error."""


async def available_models(session: aiohttp.ClientSession, token: str) -> list[dict]:
    """Discover account-specific models, without assuming a ChatGPT model alias."""
    data = await request_json(
        session, "GET", API_URL + "/models", headers={"Authorization": "Bearer " + token}
    )
    models = [
        {"value": m["slug"], "label": m.get("display_name", m["slug"])}
        for m in data.get("models", [])
        if m.get("visibility") == "list" and m.get("slug")
    ]
    if not models:
        raise ModelError("This account returned no eligible ChatGPT models.")
    return models


async def sse_events(content: Any) -> AsyncIterator[dict]:
    """Parse SSE across arbitrary chunk boundaries with a total byte limit."""
    data: list[str] = []
    total = 0
    async for raw in content:
        total += len(raw)
        if total > MAX_RESPONSE_BYTES:
            raise ModelError("The model response exceeded the size limit.")
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                if data:
                    payload = "\n".join(data)
                    data.clear()
                    if payload != "[DONE]":
                        event = json.loads(payload)
                        if not isinstance(event, dict):
                            raise ValueError
                        yield event
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        except (UnicodeError, ValueError):
            raise ModelError("The model returned an invalid stream.") from None


async def response(
    session: aiohttp.ClientSession, token: str, model: str, inputs: list[dict], tools: list[dict]
) -> dict:
    """Require a completed, bounded response before any HA tool executes."""
    payload: dict = {
        "model": model,
        "input": inputs,
        "tools": tools,
        "store": False,
        "stream": True,
        "parallel_tool_calls": False,
        "include": ["reasoning.encrypted_content"],
    }
    if len(json.dumps(payload).encode()) > MAX_INPUT_BYTES:
        raise ModelError("Conversation is too long. Start a new conversation.")
    try:
        async with session.post(
            API_URL + "/responses",
            json=payload,
            headers={"Authorization": "Bearer " + token},
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as result:
            if result.status in (401, 403):
                raise AuthError("ChatGPT authorization failed. Reauthenticate the integration.")
            if result.status == 429:
                raise ModelError("ChatGPT usage limit reached. Check ChatGPT Settings → Usage.")
            if result.status != 200:
                raise ModelError("ChatGPT rejected the request or is unavailable.")
            output_items: dict[int, dict] = {}
            async for event in sse_events(result.content):
                kind = event.get("type")
                if kind == "response.output_item.done":
                    index, item = event.get("output_index"), event.get("item")
                    if (
                        type(index) is not int
                        or not 0 <= index < 128
                        or not isinstance(item, dict)
                        or not isinstance(item.get("type"), str)
                        or (index in output_items and output_items[index] != item)
                    ):
                        raise ModelError("ChatGPT returned invalid streamed output [invalid_output_item].")
                    output_items[index] = item
                if kind in ("error", "response.failed", "response.incomplete"):
                    raise ModelError("ChatGPT did not complete the request. Check plan access and usage.")
                if kind == "response.completed":
                    completed = event.get("response", {})
                    if completed.get("status") != "completed" or not isinstance(
                        completed.get("output"), list
                    ):
                        raise ModelError("ChatGPT returned an invalid completed response.")
                    # The ChatGPT plan route may omit output from its terminal event.
                    # Complete item events carry the text, function calls and encrypted
                    # reasoning. Keep them provisional until response.completed arrives.
                    if not completed["output"] and output_items:
                        if sorted(output_items) != list(range(len(output_items))):
                            raise ModelError(
                                "ChatGPT returned incomplete streamed output [missing_output_item]."
                            )
                        completed = {**completed, "output": [output_items[i] for i in sorted(output_items)]}
                    return completed
            raise ModelError("ChatGPT disconnected before completing the request.")
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise ConnectionError(
            "Could not reach ChatGPT. Actions may already have completed; check device state before retrying."
        ) from None
