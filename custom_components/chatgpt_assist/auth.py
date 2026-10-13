"""OAuth primitives shared with the local sign-in helper (no HA imports)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
import jwt

from .const import (
    API_URL,
    AUTHORIZE_URL,
    ISSUER,
    JWKS_URL,
    NAME,
    REQUIRED_SCOPES,
    SCOPES,
    TOKEN_URL,
)


class AuthError(Exception):
    """Sanitized authentication failure."""


class ConnectionError(Exception):
    """Sanitized network failure."""


def new_attempt(host_id: str, redirect_uri: str, saved: dict | None = None) -> dict:
    """Create fresh CSRF/OIDC/PKCE values, reusing a registration if supplied."""
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": saved["client_id"] if saved else "dynamic_agent_client",
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": API_URL,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if saved:
        params["id_token_hint"] = saved["id_token"]
    else:
        params["agent_name_hint"] = NAME
    return {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": params["client_id"],
        "url": AUTHORIZE_URL + "?" + urlencode(params),
    }


def check_callback(attempt: dict, query: dict[str, str]) -> tuple[str, str]:
    """Reject CSRF, denied consent, incomplete registration, and changed clients."""
    if not secrets.compare_digest(query.get("state", ""), attempt["state"]):
        raise AuthError("The sign-in state does not match.")
    if "error" in query:
        raise AuthError("ChatGPT sign-in was denied or failed.")
    client_id = query.get("client_id", attempt["client_id"])
    if not client_id or client_id == "dynamic_agent_client":
        raise AuthError("Registration did not return an issued client ID.")
    if attempt["client_id"] != "dynamic_agent_client" and client_id != attempt["client_id"]:
        raise AuthError("Sign-in returned a different registration.")
    if not query.get("code"):
        raise AuthError("Sign-in did not return an authorization code.")
    return query["code"], client_id


async def request_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs: Any) -> dict:
    """Call a fixed HTTPS endpoint without redirects or credential-bearing errors."""
    try:
        async with session.request(
            method, url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=30), **kwargs
        ) as response:
            if response.status in (400, 401, 403):
                raise AuthError("Authorization failed. Sign in again or check plan permissions.")
            if response.status != 200:
                raise ConnectionError("The authentication service is unavailable.")
            raw = await response.content.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ConnectionError("Authentication response was too large.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError
            return data
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise ConnectionError("Could not read the authentication service response.") from None


async def verify_jwt(
    session: aiohttp.ClientSession, token: str, audience: str, nonce: str | None = None
) -> dict:
    """Verify signature, issuer, audience, required claims and optionally OIDC nonce."""
    label = "ID token" if nonce is not None else "access token"
    if not isinstance(token, str) or not token:
        raise AuthError(f"The {label} could not be verified [missing_token]. OpenAI did not return it.")
    keys = await request_json(session, "GET", JWKS_URL)
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise AuthError(f"The {label} could not be verified [unsupported_algorithm].")
        key_data = next(key for key in keys["keys"] if key["kid"] == header["kid"])
        key = jwt.PyJWK.from_dict(key_data, algorithm="RS256").key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise AuthError(f"The {label} could not be verified [nonce_mismatch].")
        return claims
    except jwt.ExpiredSignatureError:
        raise AuthError(
            f"The {label} could not be verified [expired]. Check Windows time and sign in again."
        ) from None
    except jwt.ImmatureSignatureError:
        raise AuthError(
            f"The {label} could not be verified [not_yet_valid]. Sync Windows time and sign in again."
        ) from None
    except jwt.InvalidIssuerError:
        raise AuthError(f"The {label} could not be verified [issuer_mismatch].") from None
    except jwt.InvalidAudienceError:
        raise AuthError(f"The {label} could not be verified [audience_mismatch].") from None
    except jwt.InvalidSignatureError:
        raise AuthError(f"The {label} could not be verified [invalid_signature].") from None
    except jwt.MissingRequiredClaimError as err:
        # The claim name comes from our fixed required-claims list, never token data.
        claim = err.claim if err.claim in {"exp", "iat", "iss", "aud", "sub"} else "required"
        raise AuthError(f"The {label} could not be verified [missing_{claim}_claim].") from None
    except StopIteration:
        raise AuthError(f"The {label} could not be verified [unknown_signing_key].") from None
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise AuthError(f"The {label} could not be verified [invalid_token_format].") from None


def token_record(
    response: dict, client_id: str, subject: str, host_id: str, previous: dict | None = None
) -> dict:
    """Normalize a grant; replace rotating tokens and scopes together."""
    try:
        scopes = response.get("scope", " ".join(previous["scopes"]) if previous else "").split()
        if not REQUIRED_SCOPES.issubset(scopes) or response["token_type"].lower() != "bearer":
            raise ValueError
        expires = float(response["expires_in"])
        if not 0 < expires <= 86400:
            raise ValueError
        record = {
            "client_id": client_id,
            "subject": subject,
            "ext_agent_host_id": host_id,
            "access_token": response["access_token"],
            "refresh_token": response["refresh_token"],
            "id_token": response.get("id_token", previous["id_token"] if previous else ""),
            "scopes": scopes,
            "expires_at": time.time() + expires,
            "earliest_refresh_at": response.get("earliest_refresh_at", 0),
        }
        if any(
            not isinstance(record[key], str) or not record[key]
            for key in ("client_id", "subject", "access_token", "refresh_token", "id_token")
        ):
            raise ValueError
        return record
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AuthError("The grant is incomplete or ChatGPT plan access was not granted.") from None


async def exchange(
    session: aiohttp.ClientSession, attempt: dict, query: dict, host_id: str, saved: dict | None = None
) -> dict:
    """Exchange a single-use code and validate account identity before saving."""
    code, client_id = check_callback(attempt, query)
    response = await request_json(
        session,
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": attempt["verifier"],
            "redirect_uri": attempt["redirect_uri"],
            "resource": API_URL,
        },
    )
    identity = await verify_jwt(session, response.get("id_token", ""), client_id, attempt["nonce"])
    if saved and identity["sub"] != saved["subject"]:
        raise AuthError("Sign-in returned a different account.")
    record = token_record(response, client_id, identity["sub"], host_id)
    record["email"] = identity.get("email", "ChatGPT account")
    return record


async def validate_import(session: aiohttp.ClientSession, record: dict) -> dict:
    """Verify signed access claims on import; metadata supplied by a file is untrusted."""
    try:
        claims = await verify_jwt(session, record["access_token"], API_URL)
        if (
            claims.get("client_id") != record["client_id"]
            or claims["sub"] != record["subject"]
            or not REQUIRED_SCOPES.issubset(claims.get("scope", "").split())
            or record["client_id"] == "dynamic_agent_client"
        ):
            raise AuthError("Credentials do not match the authorized account registration.")
        clean = token_record(
            {
                "access_token": record["access_token"],
                "refresh_token": record["refresh_token"],
                "id_token": record["id_token"],
                "token_type": "Bearer",
                "expires_in": claims["exp"] - time.time(),
                "scope": claims["scope"],
            },
            record["client_id"],
            claims["sub"],
            "",
        )
        # ID token may expire before access import; access token provides signed identity.
        clean["email"] = "ChatGPT account"
        return clean
    except (KeyError, TypeError):
        raise AuthError("The credential file is incomplete.") from None
