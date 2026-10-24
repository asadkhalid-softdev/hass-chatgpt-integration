"""Signed Alexa intake and independent, device-scoped spoken-answer jobs."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import html
import json
import logging
import re
import secrets
import time

import aiohttp
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alexa_security import (
    AlexaSecurityError,
    certificate_url,
    timestamp_valid,
    trusted_signer,
    verify_signature,
)
from .const import DOMAIN
from .panel import PANEL_KEY, PanelError

KEY = f"{DOMAIN}.alexa"
URL = "/api/chatgpt_assist/alexa"
DEFAULT_SKILL = "amzn1.ask.skill.c4b5f257-f4ca-485a-b1a9-80985850a3c2"
DEFAULT_LIMIT = 450  # Product policy, NOT a documented Amazon API limit.
VOICE_PROMPT = """This is a standalone voice question from an Amazon Echo, not a chat turn.
Answer the current question without referring to earlier messages. Respond in the user's language.
Your answer will be read aloud. Use natural plain text, no Markdown, tables, URLs, citations,
SSML or code. Give the answer first, with units and relevant time periods for readings.
Use available authorized tools for actual home data; never invent readings or calculations.
State missing data or uncertainty plainly. Prefer one to three short sentences.
Keep the complete spoken answer within {limit} characters, including spaces.
Do not claim a device action succeeded unless its tool result confirms it.
"""
_LOGGER = logging.getLogger(__name__)


def skill_response(text=None, *, end=True):
    response = {"shouldEndSession": end}
    if text:
        response["outputSpeech"] = {"type": "PlainText", "text": text}
        if not end:
            response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": text}}
    return {"version": "1.0", "response": response}


def spoken_text(text, limit):
    """Send plain text only, including against model-generated SSML injection."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|<[^>]*>|[*_`#|]", "", text)
    text = " ".join(text.split())
    suffix = " The full answer is in ChatGPT Assist."
    if len(text) > limit:
        prefix = text[: limit - len(suffix) - 1].rsplit(" ", 1)[0]
        text = prefix.rstrip(" ,;:") + "." + suffix
    return text


class AlexaBridge:
    def __init__(self, hass):
        self.hass = hass
        self.entries = {}
        self.settings = {}
        self.pending = {}
        self.seen = {}
        self.tasks = {}
        self.certificates = {}
        self.lock = asyncio.Lock()
        self.verify_lock = asyncio.Semaphore(2)
        self.store = Store(hass, 1, f"{DOMAIN}.alexa", private=True)

    async def load(self):
        data = await self.store.async_load() or {}
        self.settings = data.get("settings", {})
        self.pending = data.get("pending", {})
        self.seen = data.get("seen", {})

    async def save(self):
        await self.store.async_save(
            copy.deepcopy(
                {
                    "settings": self.settings,
                    "pending": self.pending,
                    "seen": self.seen,
                }
            )
        )

    def target_valid(self, target):
        entity = er.async_get(self.hass).async_get(target)
        return bool(entity and entity.platform == "alexa_media" and target.startswith("media_player."))

    def pairing_choices(self, entry_id):
        """Identify speakers by a code they say aloud, or their already paired HA name."""
        settings = self.settings.get(entry_id, {})
        registry = er.async_get(self.hass)
        choices = []
        for key, device in self.pending.items():
            if device["skill_id"] != settings.get("skill_id", DEFAULT_SKILL):
                continue
            if settings.get("account_id") and device["account_id"] != settings["account_id"]:
                continue
            target = settings.get("devices", {}).get(device["device_id"])
            if target:
                entity = registry.async_get(target)
                label = (entity.name or entity.original_name or target) if entity else target
                label += " — paired"
            else:
                code = device.get("pairing_code")
                label = f"New Echo — code {code}" if code else "Unpaired Echo — open the skill to hear a code"
                if last_seen := device.get("last_seen"):
                    heard = dt_util.as_local(dt_util.utc_from_timestamp(last_seen)).strftime("%H:%M:%S")
                    label += f" — last heard {heard}"
            choices.append((bool(target), -device.get("last_seen", 0), key, label))
        choices.sort()
        return [{"value": key, "label": label} for _, _, key, label in choices]

    async def configure(self, entry_id, values, device=None, target=None):
        """Called only by HA's authenticated administrator options flow."""
        if not isinstance(values.get("limit"), int) or not 200 <= values["limit"] <= 1000:
            raise PanelError("The spoken budget must be between 200 and 1,000 characters.")
        if values.get("enabled"):
            user = await self.hass.auth.async_get_user(values.get("user_id"))
            if not user or not user.is_active or user.system_generated:
                raise PanelError("Select an active Home Assistant user.")
            if not re.fullmatch(r"amzn1\.ask\.skill\.[a-zA-Z0-9-]+", values.get("skill_id", "")):
                raise PanelError("Enter the Alexa custom skill ID.")
            if any(
                k != entry_id and v.get("skill_id") == values["skill_id"] and v.get("enabled")
                for k, v in self.settings.items()
            ):
                raise PanelError("This skill is already assigned to another assistant.")
        async with self.lock:
            existing = self.settings.get(entry_id, {})
            values = dict(values)
            # A different skill cannot inherit an old account/device binding.
            same_skill = existing.get("skill_id") == values.get("skill_id")
            values["account_id"] = existing.get("account_id", "") if same_skill else ""
            values["devices"] = dict(existing.get("devices", {})) if same_skill else {}
            if device:
                pending = self.pending.get(device)
                if not pending or pending["skill_id"] != values["skill_id"] or not self.target_valid(target):
                    raise PanelError("Choose a discovered Echo and an Alexa Media Player entity.")
                if values["account_id"] and values["account_id"] != pending["account_id"]:
                    raise PanelError("This Echo belongs to a different Alexa account.")
                values["account_id"] = pending["account_id"]
                values["devices"][pending["device_id"]] = target
            self.settings[entry_id] = values
            await self.save()

    async def verify(self, headers, body, envelope):
        timestamp_valid(envelope)
        url = certificate_url(headers.get("SignatureCertChainUrl", ""))
        signature = headers.get("Signature-256", "")
        if not signature or len(signature) > 4096:
            raise AlexaSecurityError("Missing signature.")
        async with self.verify_lock:
            cached = self.certificates.get(url)
            if not cached or time.monotonic() - cached[0] > 3600:
                async with async_get_clientsession(self.hass).get(
                    url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=3)
                ) as response:
                    if response.status != 200:
                        raise AlexaSecurityError("Certificate unavailable.")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(4096):
                        data.extend(chunk)
                        if len(data) > 32768:
                            raise AlexaSecurityError("Certificate too large.")
                signer = await self.hass.async_add_executor_job(trusted_signer, bytes(data))
                if len(self.certificates) >= 16:
                    self.certificates.pop(next(iter(self.certificates)))
                self.certificates[url] = (time.monotonic(), signer)
            else:
                signer = cached[1]
            await self.hass.async_add_executor_job(verify_signature, signer, signature, body)

    async def accept(self, envelope):
        """Only call after signature verification. Bind identities from signed context."""
        try:
            system, request = envelope["context"]["System"], envelope["request"]
            skill, account, device, request_id = (
                system["application"]["applicationId"],
                system["user"]["userId"],
                system["device"]["deviceId"],
                request["requestId"],
            )
            if not all(
                isinstance(x, str) and 0 < len(x) <= 1024 for x in (skill, account, device, request_id)
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise AlexaSecurityError("Invalid request envelope.") from None
        async with self.lock:
            matches = [
                (key, value)
                for key, value in self.settings.items()
                if key in self.entries and value.get("enabled") and value.get("skill_id") == skill
            ]
            if len(matches) != 1:
                raise AlexaSecurityError("Skill unavailable.")
            entry_id, settings = matches[0]
            if settings.get("account_id") and account != settings["account_id"]:
                raise AlexaSecurityError("Account not authorized.")
            target = settings.get("devices", {}).get(device)
            if not target:
                key = hashlib.sha256(f"{skill}:{account}:{device}".encode()).hexdigest()
                if key not in self.pending and len(self.pending) >= 32:
                    raise AlexaSecurityError("Pairing list full.")
                discovered = self.pending.setdefault(
                    key, {"skill_id": skill, "account_id": account, "device_id": device}
                )
                if not discovered.get("pairing_code"):
                    used = {item.get("pairing_code") for item in self.pending.values()}
                    while (code := f"{secrets.randbelow(1000000):06d}") in used:
                        pass
                    discovered["pairing_code"] = code
                discovered["last_seen"] = time.time()
                await self.save()
                spoken_code = " ".join(discovered["pairing_code"])
                return skill_response(
                    f"Your pairing code is {spoken_code}. "
                    "Select this code in ChatGPT Assist's Alexa settings and choose this speaker's name."
                )
            kind = request.get("type")
            if kind == "SessionEndedRequest":
                return skill_response()
            if kind == "LaunchRequest":
                return skill_response(
                    "Ask a question. For example, say: tell me the bedroom temperature.", end=False
                )
            intent = request.get("intent", {})
            name = intent.get("name")
            if kind != "IntentRequest":
                raise AlexaSecurityError("Unsupported request.")
            if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
                return skill_response("Goodbye.")
            if name != "QuestionIntent":
                return skill_response("Say: tell me, followed by your question.", end=False)
            text = intent.get("slots", {}).get("question", {}).get("value", "")
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                return skill_response("Please ask a shorter question.")
            dedup = hashlib.sha256(f"{skill}:{account}:{request_id}".encode()).hexdigest()
            if dedup in self.seen:
                return skill_response("Your question has already been received.")
            if len(self.tasks) >= 4 or any(job[0] == device for job in self.tasks.values()):
                return skill_response("A reply is already being prepared. Please try again shortly.")
            if not self.target_valid(target) or not self.hass.services.has_service("notify", "alexa_media"):
                return skill_response("The Echo notification service is unavailable. Check Home Assistant.")
            await self.hass.data[PANEL_KEY].authorize(settings["user_id"], entry_id)
            self.seen = {key: value for key, value in self.seen.items() if time.time() - value < 86400}
            if len(self.seen) >= 1024:
                return skill_response("The daily request limit has been reached.")
            self.seen[dedup] = time.time()
            await self.save()  # Deduplicate across reload/restart; never rerun interrupted actions.
            snapshot = copy.deepcopy(settings)
            task = self.hass.async_create_background_task(
                self.run(
                    entry_id, device, target, text.strip(), dedup, request.get("locale", "en-US"), snapshot
                ),
                f"{DOMAIN} Alexa question",
            )
            self.tasks[dedup] = (device, task, entry_id)
            task.add_done_callback(lambda _task: self.tasks.pop(dedup, None))
            return skill_response("Let me check.")

    async def run(self, entry_id, device, target, text, request_id, language, snapshot):
        try:
            backend = self.hass.data[PANEL_KEY]
            # Prevent a very fast answer from talking over the skill's acknowledgement.
            started = time.monotonic()

            def valid():
                return (
                    entry_id in self.entries
                    and self.settings.get(entry_id) == snapshot
                    and snapshot.get("devices", {}).get(device) == target
                )

            answer = await backend.send_external(
                snapshot["user_id"],
                entry_id,
                text,
                request_id,
                Context(user_id=snapshot["user_id"]),
                language,
                VOICE_PROMPT.format(limit=snapshot.get("limit", DEFAULT_LIMIT)),
                valid,
            )
            if not valid():
                return
            await asyncio.sleep(max(0, 2.5 - (time.monotonic() - started)))
            await backend.authorize(snapshot["user_id"], entry_id)
            if not valid() or not self.target_valid(target):
                return
            spoken = spoken_text(answer, snapshot.get("limit", DEFAULT_LIMIT))
            # Count the escaped payload as well as the spoken text conservatively.
            while len(html.escape(spoken, quote=False)) > snapshot.get("limit", DEFAULT_LIMIT):
                spoken = spoken[:-1]
            # Escape XML even after stripping tags; never execute model-authored SSML.
            await self.hass.services.async_call(
                "notify",
                "alexa_media",
                {
                    "target": [target],
                    "message": html.escape(spoken, quote=False),
                    "data": {"type": "tts"},
                },
                blocking=True,
                context=Context(user_id=snapshot["user_id"]),
            )
            await backend.external_delivery(snapshot["user_id"], entry_id, request_id, "submitted")
        except asyncio.CancelledError:
            raise
        except Exception:
            # No automatic retries: earlier device actions/announcements may have succeeded.
            _LOGGER.warning("Alexa question or Echo delivery failed; inspect ChatGPT Assist history.")
            await self.hass.data[PANEL_KEY].external_delivery(
                snapshot["user_id"], entry_id, request_id, "failed"
            )

    async def unload(self, entry_id):
        self.entries.pop(entry_id, None)
        tasks = [job[1] for job in list(self.tasks.values()) if job[2] == entry_id]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def remove_entry(self, entry_id):
        await self.unload(entry_id)
        async with self.lock:
            settings = self.settings.pop(entry_id, {})
            self.pending = {
                key: value
                for key, value in self.pending.items()
                if value["skill_id"] != settings.get("skill_id")
            }
            await self.save()


class AlexaView(HomeAssistantView):
    url = URL
    name = "api:chatgpt_assist:alexa"
    requires_auth = False  # This route authenticates Amazon signatures, NOT HA bearer tokens.

    def __init__(self, bridge):
        self.bridge = bridge
        self.inflight = 0

    async def post(self, request):
        if self.inflight >= 4:
            return self.json_message("Busy", status_code=429)
        self.inflight += 1
        try:
            async with asyncio.timeout(6):
                body = bytearray()
                async for chunk in request.content.iter_chunked(4096):
                    body.extend(chunk)
                    if len(body) > 32768:
                        return self.json_message("Request too large", status_code=413)
                envelope = json.loads(body)
                if not isinstance(envelope, dict):
                    raise ValueError
                await self.bridge.verify(request.headers, bytes(body), envelope)
                return self.json(await self.bridge.accept(envelope))
        except (AlexaSecurityError, ValueError, KeyError, TypeError, AttributeError):
            return self.json_message("Invalid Alexa request", status_code=400)
        except (TimeoutError, aiohttp.ClientError, PanelError):
            return self.json_message("Alexa endpoint unavailable", status_code=503)
        finally:
            self.inflight -= 1


async def async_setup_alexa(hass, entry):
    async with hass.data.setdefault(f"{KEY}.setup_lock", asyncio.Lock()):
        if KEY not in hass.data:
            bridge = AlexaBridge(hass)
            await bridge.load()
            hass.http.register_view(AlexaView(bridge))
            hass.data[KEY] = bridge
        hass.data[KEY].entries[entry.entry_id] = entry
