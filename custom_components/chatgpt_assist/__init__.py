"""ChatGPT account-backed Home Assistant conversation integration."""

from __future__ import annotations

import asyncio
import time

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .administration import Administration
from .auth import AuthError, ConnectionError, request_json, token_record
from .const import API_URL, DOMAIN, TOKEN_URL

PLATFORMS = [Platform.CONVERSATION]


class Account:
    """One account/session, with serialized refresh and no credential logging."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self.lock = asyncio.Lock()
        self.options = dict(entry.options)
        self.administration = Administration(hass, entry)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.tokens")
        self.tokens = dict(entry.data)

    async def load(self) -> None:
        """Recover the latest atomically saved rotation after a restart."""
        saved = await self.store.async_load()
        if (
            saved
            and saved.get("client_id") == self.tokens["client_id"]
            and saved.get("subject") == self.tokens["subject"]
            and saved.get("expires_at", 0) > self.tokens["expires_at"]
        ):
            self.tokens = saved

    async def access_token(self) -> str:
        """Persist rotating refresh tokens before exposing the new access token."""
        async with self.lock:
            data = self.tokens
            if data["expires_at"] > time.time() + 60:
                return data["access_token"]
            earliest = data.get("earliest_refresh_at", 0)
            if isinstance(earliest, (int, float)) and earliest > time.time():
                raise ConnectionError("ChatGPT token renewal is not yet available. Try again shortly.")
            try:
                refreshed = await request_json(
                    self.session,
                    "POST",
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": data["client_id"],
                        "refresh_token": data["refresh_token"],
                        "resource": API_URL,
                    },
                )
                record = token_record(
                    refreshed, data["client_id"], data["subject"], data["ext_agent_host_id"], dict(data)
                )
            except AuthError:
                self.entry.async_start_reauth(self.hass)
                raise ConfigEntryAuthFailed("ChatGPT session expired or was revoked.") from None
            updated = {**data, **record}
            # Persist the whole rotating grant atomically before another request uses it.
            await self.store.async_save(updated)
            self.tokens = updated
            return record["access_token"]


type ChatGPTConfigEntry = ConfigEntry[Account]


async def async_setup_entry(hass: HomeAssistant, entry: ChatGPTConfigEntry) -> bool:
    """Set up a signed-in account and its conversation entity."""
    entry.runtime_data = Account(hass, entry)
    try:
        await entry.runtime_data.load()
        await entry.runtime_data.administration.load()
        await entry.runtime_data.access_token()
    except ConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from None
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_updated))
    return True


async def _updated(hass: HomeAssistant, entry: ChatGPTConfigEntry) -> None:
    """Reload on option edits, never on background token rotation."""
    if entry.runtime_data.options != dict(entry.options):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ChatGPTConfigEntry) -> bool:
    """Unload entities; session is owned by HA."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ChatGPTConfigEntry) -> None:
    """Revoke the renewable grant when an account is removed."""
    session = async_get_clientsession(hass)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.tokens")
    saved = await store.async_load()
    data = saved if saved and saved.get("expires_at", 0) > entry.data["expires_at"] else entry.data
    await store.async_remove()
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.administration", private=True).async_remove()
    try:
        discovery = await request_json(
            session, "GET", "https://auth.openai.com/.well-known/openid-configuration"
        )
        endpoint = discovery.get("revocation_endpoint", "")
        from urllib.parse import urlsplit

        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or parsed.netloc != "auth.openai.com":
            raise ConnectionError("Invalid revocation endpoint.")
        async with session.post(
            endpoint,
            data={
                "token": data["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": data["client_id"],
            },
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status == 200:
                return
    except (AuthError, ConnectionError, TimeoutError):
        pass
    except aiohttp.ClientError:
        pass
    from homeassistant.components.persistent_notification import async_create

    async_create(
        hass,
        "Local ChatGPT credentials were removed, but remote revocation was not confirmed. "
        "Disconnect ChatGPT Assist in ChatGPT Settings to revoke its access.",
        title="ChatGPT Assist disconnected",
    )
