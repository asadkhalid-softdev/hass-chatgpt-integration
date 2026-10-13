"""Transport failures must never be mistaken for completed inference."""

import json

import pytest

from custom_components.chatgpt_assist import api
from custom_components.chatgpt_assist.auth import AuthError


class Content:
    def __init__(self, events):
        self.lines = (
            ("".join("data: " + json.dumps(event) + "\r\n\r\n" for event in events))
            .encode()
            .splitlines(keepends=True)
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.lines:
            raise StopAsyncIteration
        return self.lines.pop(0)


class Session:
    def __init__(self, events, status=200):
        self.events, self.status = events, status

    def post(self, url, **kwargs):
        self.payload, self.kwargs = kwargs["json"], kwargs
        return self

    async def __aenter__(self):
        self.content = Content(self.events)
        return self

    async def __aexit__(self, *args):
        return False


async def test_required_preview_fields_and_complete_output():
    session = Session([{"type": "response.completed", "response": {"status": "completed", "output": []}}])
    assert (await api.response(session, "secret", "model", [], []))["output"] == []
    assert session.payload["store"] is False
    assert session.payload["stream"] is True
    assert session.kwargs["allow_redirects"] is False
    assert not {"temperature", "max_output_tokens", "previous_response_id"} & session.payload.keys()


@pytest.mark.parametrize(
    "events", [[], [{"type": "response.failed"}], [{"type": "response.incomplete"}], [{"type": "error"}]]
)
async def test_failed_or_truncated_stream(events):
    with pytest.raises(api.ModelError):
        await api.response(Session(events), "secret", "model", [], [])


@pytest.mark.parametrize(
    "status,exception",
    [(401, AuthError), (403, AuthError), (429, api.ModelError), (500, api.ModelError), (302, api.ModelError)],
)
async def test_status_failures(status, exception):
    with pytest.raises(exception):
        await api.response(Session([], status), "secret", "model", [], [])


async def test_size_limit(monkeypatch):
    monkeypatch.setattr(api, "MAX_RESPONSE_BYTES", 8)
    with pytest.raises(api.ModelError):
        await api.response(Session([{"type": "response.completed"}]), "secret", "model", [], [])


async def test_terminal_empty_output_uses_completed_items_in_order():
    message = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hello"}]}
    reasoning = {"type": "reasoning", "summary": [], "encrypted_content": "opaque"}
    session = Session(
        [
            {"type": "response.output_item.done", "output_index": 1, "item": message},
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            {"type": "response.completed", "response": {"status": "completed", "output": []}},
        ]
    )
    assert (await api.response(session, "secret", "model", [], []))["output"] == [reasoning, message]


@pytest.mark.parametrize("terminal", [{"type": "response.failed"}, {"type": "response.incomplete"}, None])
async def test_streamed_tool_calls_are_not_returned_before_success(terminal):
    call = {"type": "function_call", "name": "test", "arguments": "{}", "call_id": "call1"}
    events = [{"type": "response.output_item.done", "output_index": 0, "item": call}]
    if terminal:
        events.append(terminal)
    with pytest.raises(api.ModelError):
        await api.response(Session(events), "secret", "model", [], [])


async def test_gaps_in_completed_output_are_rejected():
    events = [
        {"type": "response.output_item.done", "output_index": 1, "item": {"type": "message"}},
        {"type": "response.completed", "response": {"status": "completed", "output": []}},
    ]
    with pytest.raises(api.ModelError, match=r"\[missing_output_item\]"):
        await api.response(Session(events), "secret", "model", [], [])
