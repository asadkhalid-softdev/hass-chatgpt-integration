#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "aiohttp>=3.13.3,<4",
#     "PyJWT[crypto]==2.10.1",
#     "pywin32==312; sys_platform == 'win32'",
# ]
# ///
"""Complete documented ChatGPT OSS OAuth in a local browser, without HA secrets."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import secrets
import sys
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import aiohttp
from aiohttp import web

# Load only shared OAuth modules, bypassing the HA package initializer.
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_chatgpt_oauth"
spec = importlib.util.spec_from_file_location(
    PACKAGE,
    ROOT / "custom_components/chatgpt_assist/const.py",
    submodule_search_locations=[str(ROOT / "custom_components/chatgpt_assist")],
)
module = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = module
spec.loader.exec_module(module)
from _chatgpt_oauth.auth import AuthError, ConnectionError, exchange, new_attempt  # noqa: E402


def _protect_windows_file(path: str) -> None:
    """Remove inherited access and grant only the current Windows account access."""
    try:
        import ntsecuritycon
        import pywintypes
        import win32api
        import win32con
        import win32security
    except ImportError:
        raise OSError("Windows credential protection requires pywin32. Run this helper with uv.") from None
    try:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
        win32security.SetNamedSecurityInfo(
            path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        security = win32security.GetNamedSecurityInfo(
            path, win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
        actual = security.GetSecurityDescriptorDacl()
        control = security.GetSecurityDescriptorControl()[0]
        if (
            not control & win32security.SE_DACL_PROTECTED
            or actual is None
            or actual.GetAceCount() != 1
            or actual.GetAce(0)[2] != sid
        ):
            raise OSError("Windows did not enforce private credential permissions.")
    except pywintypes.error:
        raise OSError("Could not protect credentials. Use a private folder on an NTFS drive.") from None


def atomic_private_write(path: Path, data: dict) -> None:
    """Write credentials atomically, protecting the empty file before writing secrets."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".chatgpt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            if os.name == "nt":
                _protect_windows_file(temporary)
            else:
                os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def login(args) -> None:
    path = args.output.expanduser().resolve()
    saved = json.loads(path.read_text()) if path.exists() else None
    host_path = path.with_suffix(".host.json")
    if args.host_id:
        host_id = args.host_id
    elif host_path.exists():
        host_id = json.loads(host_path.read_text())["id"]
    else:
        host_id = "urn:uuid:" + str(uuid4())
    # Persist before authorization; keep it separate from account registrations.
    atomic_private_write(host_path, {"id": host_id})
    completed = asyncio.get_running_loop().create_future()
    pending = {}

    async def callback(request):
        if request.host != pending["host"]:
            return web.Response(status=400, text="Invalid callback host.")
        values = parse_qs(request.query_string)
        if any(len(v) != 1 for v in values.values()):
            return web.Response(status=400, text="Duplicate callback parameters.")
        query = {k: v[0] for k, v in values.items()}
        if not secrets.compare_digest(query.get("state", ""), pending["attempt"]["state"]):
            return web.Response(status=400, text="Invalid sign-in state.")
        if completed.done():
            return web.Response(status=409, text="Callback already used.")
        completed.set_result(query)
        return web.Response(
            text="Sign-in received. Return to the terminal to check the result.",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'",
            },
        )

    app = web.Application(client_max_size=8192)
    app.router.add_get("/auth/callback", callback)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        pending["host"] = f"127.0.0.1:{port}"
        attempt = new_attempt(host_id, f"http://127.0.0.1:{port}/auth/callback", saved)
        pending["attempt"] = attempt
        print("Continue with ChatGPT: opening your browser. Complete sign-in and consent there.")
        if args.no_browser:
            # Returning URLs contain an ID-token hint. Never print that credential.
            url = attempt["url"]
            if saved:
                parsed = urlsplit(url)
                from urllib.parse import urlencode

                query = parse_qs(parsed.query)
                query.pop("id_token_hint", None)
                url = parsed._replace(query=urlencode({k: v[0] for k, v in query.items()})).geturl()
            print(url)
        else:
            opened = await asyncio.to_thread(webbrowser.open, attempt["url"])
            if not opened:
                raise AuthError("No browser opened. Run again with --no-browser on your browser's computer.")
        query = await asyncio.wait_for(completed, 300)
        async with aiohttp.ClientSession() as session:
            record = await exchange(session, attempt, query, host_id, saved)
        atomic_private_write(path, record)
        print(f"Sign-in verified. Protected credentials saved to: {path}")
        print("Import this file's JSON into ChatGPT Assist in Home Assistant over HTTPS.")
        print("After import, let Home Assistant own refreshes. Do not share or log this file.")
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path.home() / ".config/chatgpt-assist/chatgpt-account.json"
    )
    parser.add_argument("--host-id", help="HA host ID from diagnostics, for reauthorization")
    parser.add_argument(
        "--no-browser", action="store_true", help="Print the authorization URL for manual opening"
    )
    args = parser.parse_args()
    try:
        asyncio.run(login(args))
    except (AuthError, ConnectionError) as err:
        parser.exit(1, str(err) + "\n")
    except TimeoutError:
        parser.exit(1, "Sign-in timed out. Run the helper again.\n")
    except KeyboardInterrupt:
        parser.exit(1, "Sign-in cancelled.\n")
    except (ValueError, OSError, KeyError):
        parser.exit(
            1,
            "Could not read or save protected credentials. Check permissions and use a local NTFS folder on Windows.\n",
        )


if __name__ == "__main__":
    main()
