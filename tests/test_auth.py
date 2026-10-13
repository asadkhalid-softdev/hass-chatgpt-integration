"""Security checks on OAuth state, identity, grant scopes and token rotation."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from custom_components.chatgpt_assist import Account, auth
from custom_components.chatgpt_assist.const import API_URL, ISSUER, REQUIRED_SCOPES
from scripts.chatgpt_login import atomic_private_write


def grant(**kwargs):
    return {
        "access_token": "access",
        "refresh_token": "refresh",
        "id_token": "identity",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": " ".join(REQUIRED_SCOPES),
        **kwargs,
    }


def test_pkce_state_and_returning_client():
    from urllib.parse import parse_qs, urlsplit

    attempt = auth.new_attempt("urn:uuid:host", "http://127.0.0.1:1234/auth/callback")
    params = parse_qs(urlsplit(attempt["url"]).query)
    assert params["client_id"] == ["dynamic_agent_client"]
    assert params["code_challenge_method"] == ["S256"]
    assert attempt["verifier"] not in attempt["url"]
    with pytest.raises(auth.AuthError):
        auth.check_callback(attempt, {"state": "wrong", "code": "secret", "client_id": "issued"})
    with pytest.raises(auth.AuthError):
        auth.check_callback(attempt, {"state": attempt["state"], "code": "secret"})
    assert auth.check_callback(
        attempt, {"state": attempt["state"], "code": "secret", "client_id": "issued"}
    ) == ("secret", "issued")
    attempt["client_id"] = "issued"
    with pytest.raises(auth.AuthError):
        auth.check_callback(attempt, {"state": attempt["state"], "code": "secret", "client_id": "other"})
    with pytest.raises(auth.AuthError):
        auth.check_callback(attempt, {"state": attempt["state"], "error": "access_denied"})


async def test_jwt_verification(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "test"
    monkeypatch.setattr(auth, "request_json", AsyncMock(return_value={"keys": [jwk]}))
    claims = {
        "sub": "account",
        "iss": ISSUER,
        "aud": "issued",
        "exp": int(time.time()) + 100,
        "iat": int(time.time()),
        "nonce": "nonce",
    }

    def signed(changes=None):
        return jwt.encode({**claims, **(changes or {})}, private, algorithm="RS256", headers={"kid": "test"})

    assert (await auth.verify_jwt(None, signed(), "issued", "nonce"))["sub"] == "account"
    for changes in [{"iss": "https://evil.example"}, {"aud": "other"}, {"exp": 1}, {"nonce": "other"}]:
        with pytest.raises(auth.AuthError):
            await auth.verify_jwt(None, signed(changes), "issued", "nonce")
    forged = jwt.encode(claims, "fake", algorithm="HS256", headers={"kid": "test"})
    with pytest.raises(auth.AuthError):
        await auth.verify_jwt(None, forged, "issued", "nonce")


def test_grant_requires_permissions():
    with pytest.raises(auth.AuthError):
        auth.token_record(grant(scope="openid email"), "issued", "sub", "host")
    record = auth.token_record(grant(), "issued", "sub", "host")
    assert record["expires_at"] > time.time()
    assert (
        auth.token_record(grant(refresh_token="new"), "issued", "sub", "host", record)["refresh_token"]
        == "new"
    )


async def test_import_signed_identity_and_scopes(monkeypatch):
    record = auth.token_record(grant(), "issued", "sub", "host")
    claims = {
        "sub": "sub",
        "client_id": "issued",
        "scope": " ".join(REQUIRED_SCOPES),
        "exp": time.time() + 500,
    }
    verify = AsyncMock(return_value=claims)
    monkeypatch.setattr(auth, "verify_jwt", verify)
    clean = await auth.validate_import(None, record)
    assert clean["ext_agent_host_id"] == ""  # laptop host cannot replace HA's host
    verify.assert_awaited_once_with(None, "access", API_URL)
    for changes in [{"sub": "other"}, {"client_id": "other"}, {"scope": "openid"}]:
        verify.return_value = {**claims, **changes}
        with pytest.raises(auth.AuthError):
            await auth.validate_import(None, record)


async def test_refresh_serializes_and_saves_before_use(monkeypatch):
    import custom_components.chatgpt_assist as integration

    account = object.__new__(Account)
    account.lock = asyncio.Lock()
    account.tokens = auth.token_record(grant(), "issued", "sub", "host")
    account.tokens["expires_at"] = 0
    account.entry = SimpleNamespace(async_start_reauth=lambda hass: None)
    account.session = None
    account.hass = None
    account.store = SimpleNamespace(async_save=AsyncMock())
    call = AsyncMock(return_value=grant(access_token="new", refresh_token="rotated"))
    monkeypatch.setattr(integration, "request_json", call)
    assert await asyncio.gather(account.access_token(), account.access_token()) == ["new", "new"]
    assert call.await_count == 1
    account.store.async_save.assert_awaited_once()
    assert account.tokens["refresh_token"] == "rotated"


def test_private_atomic_file(tmp_path):
    path = tmp_path / "credentials.json"
    atomic_private_write(path, {"refresh_token": "secret"})
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {"refresh_token": "secret"}


async def test_restore_uses_newest_matching_session():
    account = object.__new__(Account)
    account.tokens = {"client_id": "issued", "subject": "sub", "expires_at": 10}
    saved = {"client_id": "issued", "subject": "sub", "expires_at": 100, "refresh_token": "rotated"}
    account.store = SimpleNamespace(async_load=AsyncMock(return_value=saved))
    await account.load()
    assert account.tokens["refresh_token"] == "rotated"
    account.store.async_load.return_value = {**saved, "subject": "other", "expires_at": 1000}
    await account.load()
    assert account.tokens["subject"] == "sub"


async def test_revoked_refresh_starts_reauth(monkeypatch):
    from unittest.mock import Mock

    from homeassistant.exceptions import ConfigEntryAuthFailed

    import custom_components.chatgpt_assist as integration

    account = object.__new__(Account)
    account.lock = asyncio.Lock()
    account.tokens = auth.token_record(grant(), "issued", "sub", "host")
    account.tokens["expires_at"] = 0
    account.entry = SimpleNamespace(async_start_reauth=Mock())
    account.session, account.hass = None, None
    account.store = SimpleNamespace(async_save=AsyncMock())
    monkeypatch.setattr(integration, "request_json", AsyncMock(side_effect=auth.AuthError("revoked")))
    with pytest.raises(ConfigEntryAuthFailed):
        await account.access_token()
    account.entry.async_start_reauth.assert_called_once()
    account.store.async_save.assert_not_awaited()
