"""Read OAuth JSON through EOF and stop before exceeding the size cap."""

import asyncio
import json
import sys

import aiohttp
import pytest
from aiohttp import web

# Shared auth is loaded by the standalone helper without importing Home Assistant.
from scripts import chatgpt_login

auth = sys.modules[chatgpt_login.PACKAGE + ".auth"]


@pytest.mark.parametrize(
    "body", [b'{"access_token":"example","scope":"openid"}', b'{"keys":[{"kid":"example"}]}']
)
async def test_real_split_http_response(body):
    async def handler(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        for chunk in [body[:3], body[3:10], body[10:]]:
            await response.write(chunk)
            await asyncio.sleep(0.01)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/", handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            assert await auth.request_json(session, "GET", f"http://127.0.0.1:{port}/") == json.loads(body)
    finally:
        await runner.cleanup()


class Content:
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk


class Session:
    def __init__(self, content):
        self.content = content
        self.status = 200

    def request(self, *args, **kwargs):
        assert kwargs["allow_redirects"] is False
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_oversize_stops_reading(monkeypatch):
    monkeypatch.setattr(auth, "MAX_AUTH_RESPONSE_BYTES", 8)
    content = Content([b"12345", b"67890", b"never-read"])
    with pytest.raises(auth.ConnectionError, match=r"\[response_too_large\]"):
        await auth.request_json(Session(content), "GET", auth.JWKS_URL)
    assert content.read_count == 2


@pytest.mark.parametrize("body", [b"", b"<html>private-network-data</html>", b"[]", b"\xff"])
async def test_invalid_body_sanitized(body):
    with pytest.raises(auth.ConnectionError, match=r"\[invalid_json\]") as error:
        await auth.request_json(Session(Content([body])), "GET", auth.TOKEN_URL)
    assert "private-network-data" not in str(error.value)
    assert "token service" in str(error.value)
