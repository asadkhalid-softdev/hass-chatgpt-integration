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


PROVIDER_MESSAGES = {
    "subscription_sharing_user_not_eligible": "ChatGPT plan access is unavailable for this account or workspace.",
    "subscription_sharing_usage_limit_exceeded": "ChatGPT app or plan usage limit reached. Review ChatGPT Settings → Usage.",
    "subscription_sharing_usage_unavailable": "ChatGPT could not check usage availability. Try again later.",
    "subscription_sharing_unsupported_capability": "A model or request feature is unsupported for ChatGPT plan access.",
    "subscription_sharing_route_not_supported": "OpenAI rejected this ChatGPT plan API route.",
    "subscription_sharing_invalid_user": "OpenAI could not validate the subscriber context.",
    "subscription_sharing_user_unavailable": "ChatGPT account or workspace information is temporarily unavailable.",
    "chatpass_v2_scope_not_authorized": "The ChatGPT grant does not authorize this operation.",
    "chatpass_v2_invalid_authorization_context": "OpenAI rejected the grant authorization context.",
    "rate_limit_exceeded": "OpenAI rate limit reached. Try again later.",
    "insufficient_quota": "OpenAI reports insufficient usage allowance. Review ChatGPT Settings → Usage.",
    "model_not_found": "The selected model is unavailable. Choose an account model in Configure.",
    "unsupported_model": "The selected model does not support this request.",
    "unsupported_parameter": "OpenAI rejected an unsupported request parameter.",
    "unsupported_value": "OpenAI rejected a request parameter value.",
    "invalid_request_error": "OpenAI rejected the request format.",
    "invalid_request": "OpenAI rejected the request format.",
    "invalid_prompt": "OpenAI rejected the conversation input. Start a new conversation.",
    "invalid_encrypted_content": "OpenAI rejected saved reasoning context. Start a new conversation.",
    "context_length_exceeded": "Conversation context is too long. Start a new conversation.",
    "server_error": "OpenAI had an internal service error. Try again later.",
    "internal_error": "OpenAI had an internal service error. Try again later.",
    "permission_denied": "OpenAI denied this operation. Check account and workspace permissions.",
    "content_filter": "OpenAI stopped the response under its content policy.",
    "invalid_api_key": "ChatGPT authorization failed. Reauthenticate the integration.",
}


def provider_error(payload: dict, stage: str, status: int | None = None) -> Exception:
    """Keep only known codes/parameter roots; never echo provider messages or details."""
    response_data = payload.get("response")
    source = response_data if isinstance(response_data, dict) else payload
    error = source.get("error")
    error = error if isinstance(error, dict) else source
    code = error.get("code") or error.get("type")
    recognized = isinstance(code, str) and code in PROVIDER_MESSAGES
    tag = code if recognized else stage
    message = PROVIDER_MESSAGES[code] if recognized else "OpenAI did not complete the request."
    if status == 429 and not recognized:
        message = "OpenAI usage or rate limit reached. Review ChatGPT Settings → Usage."
    elif status == 403 and not recognized:
        message = "OpenAI denied admission. Check ChatGPT plan permissions and serving-region policy."
    elif status is not None and status >= 500 and not recognized:
        message = "OpenAI is temporarily unavailable. Try again later."
    parameter = error.get("param")
    roots = {
        "model",
        "input",
        "tools",
        "include",
        "reasoning",
        "parallel_tool_calls",
        "store",
        "stream",
        "service_tier",
        "tool_choice",
    }
    # Dynamic schema property names and user content must never be copied to the UI.
    if isinstance(parameter, str):
        root = parameter.split(".", 1)[0].split("[", 1)[0]
        if root in roots:
            tag += "; parameter=" + root
    details = source.get("incomplete_details")
    if (
        isinstance(details, dict)
        and isinstance(details.get("reason"), str)
        and details["reason"] in {"max_output_tokens", "content_filter"}
    ):
        tag += "; reason=" + details["reason"]
    if status is not None:
        tag += "; http=" + str(status)
    if status == 401 or code == "invalid_api_key":
        return AuthError("ChatGPT authorization failed. Reauthenticate the integration. [" + tag + "]")
    return ModelError(message + " [" + tag + "]")


async def error_body(content: Any) -> dict:
    """Read a bounded error body for classification, never logging or returning it."""
    raw = bytearray()
    async for chunk in content.iter_chunked(8192):
        if len(raw) + len(chunk) > 64_000:
            return {}
        raw.extend(chunk)
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except (ValueError, UnicodeError):
        return {}


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
            if result.status != 200:
                body = await error_body(result.content)
                raise provider_error(body, "http_error", result.status)
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
                    raise provider_error(event, kind.replace(".", "_"))
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
