"""Alexa signature boundaries, exact-device jobs and context-free sidebar transcripts."""

import asyncio
import base64
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.http import current_request

from custom_components.chatgpt_assist import alexa, alexa_security
from custom_components.chatgpt_assist.config_flow import ChatGPTOptionsFlow
from custom_components.chatgpt_assist.panel import PanelError
from tests.test_panel import chat  # noqa: F401 -- reuse a real Core chat-session fixture

TEST_SKILL_ID = "amzn1.ask.skill.00000000-0000-0000-0000-000000000000"


def envelope(device="echo-one", account="amazon-user", request="request-one", kind="IntentRequest"):
    return {
        "version": "1.0",
        "context": {
            "System": {
                "application": {"applicationId": TEST_SKILL_ID},
                "user": {"userId": account},
                "device": {"deviceId": device},
            }
        },
        "request": {
            "type": kind,
            "requestId": request,
            "locale": "en-US",
            "timestamp": datetime.now(UTC).isoformat(),
            "intent": {"name": "QuestionIntent", "slots": {"question": {"value": "bedroom temperature"}}},
        },
    }


@pytest.fixture
async def bridge(chat):  # noqa: F811 -- pytest resolves the imported fixture
    hass, backend, entry, users, calls = chat
    player = er.async_get(hass).async_get_or_create("media_player", "alexa_media", "speaker-one")
    hass.states.async_set(player.entity_id, "idle")
    notifications = []

    async def notify(call):
        notifications.append(dict(call.data))

    hass.services.async_register("notify", "alexa_media", notify)
    manager = alexa.AlexaBridge(hass)
    manager.entries[entry.entry_id] = entry
    settings = {"enabled": True, "skill_id": TEST_SKILL_ID, "user_id": "one", "limit": 450}
    await manager.configure(entry.entry_id, settings)
    # Discovery cannot generate anything. An administrator must pair the exact device/account.
    await manager.accept(envelope(kind="LaunchRequest"))
    await manager.configure(entry.entry_id, settings, next(iter(manager.pending)), player.entity_id)
    yield manager, hass, backend, entry, users, calls, notifications, player.entity_id
    await manager.unload(entry.entry_id)


async def finish(manager):
    await asyncio.gather(*(job[1] for job in list(manager.tasks.values())))


@pytest.mark.parametrize(
    "kind,name",
    [
        ("LaunchRequest", None),
        ("IntentRequest", "AMAZON.HelpIntent"),
        ("IntentRequest", "AMAZON.FallbackIntent"),
        ("IntentRequest", "QuestionIntent"),
    ],
)
async def test_launch_and_recovery_collect_question_without_starting_a_job(bridge, kind, name):
    manager, _, _, _, _, calls, notifications, _ = bridge
    request = envelope(kind=kind)
    request["request"]["intent"] = {"name": name, "slots": {}}
    result = (await manager.accept(request))["response"]
    assert result["shouldEndSession"] is False
    directive = result["directives"][0]
    assert directive["type"] == "Dialog.ElicitSlot"
    assert directive["slotToElicit"] == "question"
    assert directive["updatedIntent"]["name"] == "QuestionIntent"
    assert "value" not in directive["updatedIntent"]["slots"]["question"]
    assert not calls and not notifications and not manager.tasks and not manager.seen


@pytest.mark.parametrize(
    "question",
    [
        "When was the last time work heater turned on",
        "How long was the work heater on yesterday",
        "Is the bedroom warmer than yesterday",
        "Compare the bedroom and kitchen temperatures",
    ],
)
async def test_elicited_natural_question_reaches_agent_without_losing_words(bridge, monkeypatch, question):
    manager, _, backend, _, _, _, _, _ = bridge
    send = AsyncMock(return_value="Answer.")
    monkeypatch.setattr(backend, "send_external", send)
    await manager.accept(envelope(kind="LaunchRequest"))
    request = envelope()
    request["request"]["dialogState"] = "IN_PROGRESS"
    request["request"]["intent"]["slots"]["question"]["value"] = question
    response = (await manager.accept(request))["response"]
    assert response["shouldEndSession"] is True
    assert "directives" not in response
    await finish(manager)
    assert send.call_args.args[2] == question


@pytest.mark.parametrize("name", ["AMAZON.StopIntent", "AMAZON.CancelIntent"])
async def test_stop_while_collecting_question_does_not_elicit_or_generate(bridge, name):
    manager, _, _, _, _, calls, notifications, _ = bridge
    await manager.accept(envelope(kind="LaunchRequest"))
    request = envelope()
    request["request"]["intent"] = {"name": name}
    response = (await manager.accept(request))["response"]
    assert response["shouldEndSession"] is True
    assert "directives" not in response
    assert not manager.tasks and not calls and not notifications


def test_bundled_model_supports_elicitation_without_invalid_bare_intent_sample():
    model = json.loads((Path(__file__).parents[1] / "docs/alexa/en-US.json").read_text())["interactionModel"]
    question = next(i for i in model["languageModel"]["intents"] if i["name"] == "QuestionIntent")
    assert question["slots"][0]["samples"] == ["{question}"]
    assert "{question}" not in question["samples"]
    assert "when was {question}" in question["samples"]
    assert model["dialog"]["delegationStrategy"] == "SKILL_RESPONSE"
    slot = model["dialog"]["intents"][0]["slots"][0]
    assert slot["name"] == "question" and slot["elicitationRequired"] is True
    assert slot["prompts"]["elicitation"] in {p["id"] for p in model["prompts"]}


async def test_voice_has_no_history_and_does_not_mutate_chat_inference_context(bridge):
    manager, _, backend, _, _, calls, notifications, target = bridge
    await backend.send("one", "account", "private earlier chat", "chat-1", Context(user_id="one"))
    before = copy.deepcopy(next(iter(backend.records.values()))["context"])
    reply = await manager.accept(envelope())
    assert reply["response"]["shouldEndSession"] is True
    assert notifications == []  # Acknowledge without waiting for inference/TTS.
    await finish(manager)
    assert [item for item in calls[-1]["inputs"] if item.get("role") == "user"] == [
        {"role": "user", "content": "bedroom temperature"}
    ]
    assert calls[-1]["context"].user_id == "one"
    record = next(iter(backend.records.values()))
    assert record["context"] == before
    assert record["messages"][-1]["source"] == "alexa"
    assert record["messages"][-1]["delivery"] == "submitted"
    assert notifications == [{"target": [target], "message": "A helpful answer.", "data": {"type": "tts"}}]
    await manager.accept(envelope(request="second"))
    await finish(manager)
    assert sum(item.get("role") == "user" for item in calls[-1]["inputs"]) == 1
    await backend.send("one", "account", "ordinary follow up", "chat-2", Context(user_id="one"))
    assert {"role": "user", "content": "private earlier chat"} in calls[-1]["inputs"]
    assert {"role": "user", "content": "bedroom temperature"} not in calls[-1]["inputs"]
    assert len(notifications) == 2  # Ordinary chat never speaks.
    assert len((await backend.history("one", "account"))["messages"]) == 8
    assert (await backend.history("two", "account"))["messages"] == []


async def test_voice_prompt_is_separate_and_sent_only_for_external_requests(bridge, monkeypatch):
    manager, _, backend, _, _, _, _, _ = bridge
    original = conversation.async_converse
    kwargs_seen = []

    async def capture(*args, **kwargs):
        kwargs_seen.append(kwargs)
        return await original(*args, **kwargs)

    monkeypatch.setattr(conversation, "async_converse", capture)
    await manager.accept(envelope())
    await finish(manager)
    assert "450 characters" in kwargs_seen[-1]["extra_system_prompt"]
    await backend.send("one", "account", "normal", "normal", Context(user_id="one"))
    assert "extra_system_prompt" not in kwargs_seen[-1]


async def test_real_agent_and_core_prompt_receive_voice_instructions_without_history(bridge, monkeypatch):
    from homeassistant.components.conversation import agent_manager
    from homeassistant.components.conversation.const import DATA_COMPONENT

    from custom_components.chatgpt_assist import conversation as agent_module
    from custom_components.chatgpt_assist.const import DOMAIN

    manager, hass, backend, entry, users, _, notifications, _ = bridge
    entry.options.update(control=False, logs_access=False, reasoning_effort="low")
    for user in users.values():
        user.name = user.id
    entry.runtime_data = SimpleNamespace(session=None, access_token=AsyncMock(return_value="test-token"))
    entity = agent_module.ChatGPTConversation(entry)
    entity.hass = hass
    entity.entity_id = er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    hass.data[DATA_COMPONENT] = SimpleNamespace(
        get_entity=lambda identifier: entity if identifier == entity.entity_id else None
    )
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)
    monkeypatch.setattr(conversation, "async_converse", agent_manager.async_converse)
    provider = AsyncMock(
        return_value={
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "The bedroom is 21 degrees Celsius."}],
                }
            ]
        }
    )
    monkeypatch.setattr(agent_module, "response", provider)
    await backend.send("one", "account", "private chat secret", "chat", Context(user_id="one"))
    await manager.accept(envelope())
    await finish(manager)
    inputs = provider.call_args.args[3]
    assert provider.call_args.kwargs == {"reasoning_effort": "low"}
    assert "standalone voice question" in inputs[0]["content"]
    assert "450 characters" in inputs[0]["content"]
    assert [item for item in inputs if item.get("role") == "user"] == [
        {"role": "user", "content": "bedroom temperature"}
    ]
    assert len(notifications) == 1
    await backend.send("one", "account", "normal follow up", "chat-2", Context(user_id="one"))
    normal_inputs = provider.call_args.args[3]
    assert provider.call_args.kwargs == {"reasoning_effort": "low"}
    assert "standalone voice question" not in normal_inputs[0]["content"]
    assert {"role": "user", "content": "private chat secret"} in normal_inputs
    assert len(notifications) == 1


async def test_account_device_skill_replay_and_reload_fail_closed(bridge):
    manager, hass, _, _, _, calls, notifications, _ = bridge
    with pytest.raises(alexa_security.AlexaSecurityError):
        await manager.accept(envelope(account="attacker"))
    wrong = envelope()
    wrong["context"]["System"]["application"]["applicationId"] = "another-skill"
    with pytest.raises(alexa_security.AlexaSecurityError):
        await manager.accept(wrong)
    await manager.accept(envelope(device="unpaired-echo"))
    assert not calls and not notifications
    await manager.accept(envelope())
    await finish(manager)
    await manager.accept(envelope())
    assert len(calls) == 1
    recovered = alexa.AlexaBridge(hass)
    await recovered.load()
    recovered.entries = manager.entries
    await recovered.accept(envelope())
    assert not recovered.tasks
    assert len(calls) == 1


async def test_disable_while_generating_prevents_notification(bridge, monkeypatch):
    manager, _, backend, _, _, _, notifications, _ = bridge
    started, release = asyncio.Event(), asyncio.Event()
    original = backend.send_external

    async def delayed(*args):
        started.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(backend, "send_external", delayed)
    await manager.accept(envelope())
    await started.wait()
    manager.settings["account"]["enabled"] = False
    release.set()
    await finish(manager)
    assert not notifications


async def test_delivery_failure_is_visible_and_does_not_retry(bridge, monkeypatch):
    manager, hass, backend, _, _, calls, _, _ = bridge

    async def fail_delivery(call):
        raise RuntimeError("Delivery failed")

    hass.services.async_register("notify", "alexa_media", fail_delivery)
    await manager.accept(envelope())
    await finish(manager)
    assert (await backend.history("one", "account"))["messages"][-1]["delivery"] == "failed"
    await manager.accept(envelope())
    assert len(calls) == 1


async def test_pairing_rejects_foreign_player_and_inactive_actor(bridge):
    manager, hass, _, _, users, _, _, _ = bridge
    unrelated = er.async_get(hass).async_get_or_create("media_player", "other", "unrelated")
    settings = {"enabled": True, "skill_id": TEST_SKILL_ID, "user_id": "one", "limit": 450}
    with pytest.raises(PanelError):
        await manager.configure("account", settings, next(iter(manager.pending)), unrelated.entity_id)
    users["one"].is_active = False
    with pytest.raises(PanelError):
        await manager.configure("account", settings)


async def test_pairing_codes_are_spoken_stable_unique_and_not_authorization(bridge, monkeypatch):
    manager, _, _, _, _, calls, notifications, target = bridge
    # Make the collision test deterministic without depending on a randomly generated fixture code.
    next(iter(manager.pending.values()))["pairing_code"] = "999999"
    numbers = iter([123456, 123456, 789012])
    monkeypatch.setattr(alexa.secrets, "randbelow", lambda maximum: next(numbers))
    reply = await manager.accept(envelope(device="kitchen", kind="LaunchRequest"))
    assert "1 2 3 4 5 6" in reply["response"]["outputSpeech"]["text"]
    assert not calls and not notifications
    repeated = await manager.accept(envelope(device="kitchen", kind="LaunchRequest"))
    assert repeated == reply
    other = await manager.accept(envelope(device="bedroom", kind="LaunchRequest"))
    assert "7 8 9 0 1 2" in other["response"]["outputSpeech"]["text"]
    with pytest.raises(PanelError):
        await manager.configure(
            "account",
            {
                "enabled": True,
                "skill_id": TEST_SKILL_ID,
                "user_id": "one",
                "limit": 450,
            },
            "123456",
            target,
        )
    assert not calls and not notifications


async def test_pairing_choices_show_names_latest_codes_and_preserve_legacy_bindings(bridge):
    manager, hass, _, _, _, _, _, target = bridge
    registry = er.async_get(hass)
    registry.async_update_entity(target, name="Work Room Echo")
    original_mapping = copy.deepcopy(manager.settings["account"]["devices"])
    # Simulate pre-code storage, as exists on already installed 0.7.0 instances.
    next(iter(manager.pending.values())).pop("pairing_code", None)
    next(iter(manager.pending.values())).pop("last_seen", None)
    await manager.accept(envelope(device="kitchen", kind="LaunchRequest"))
    kitchen_key = next(key for key, value in manager.pending.items() if value["device_id"] == "kitchen")
    manager.pending[kitchen_key]["last_seen"] = 100
    await manager.accept(envelope(device="bedroom", kind="LaunchRequest"))
    bedroom_key = next(key for key, value in manager.pending.items() if value["device_id"] == "bedroom")
    manager.pending[bedroom_key]["last_seen"] = 200
    manager.pending["foreign"] = {
        "skill_id": TEST_SKILL_ID,
        "account_id": "another-account",
        "device_id": "foreign",
    }
    choices = manager.pairing_choices("account")
    assert [choice["value"] for choice in choices[:2]] == [bedroom_key, kitchen_key]
    assert "New Echo — code " in choices[0]["label"]
    assert "last heard" in choices[0]["label"]
    assert choices[-1]["label"] == "Work Room Echo — paired"
    assert len(choices) == 3
    await manager.save()
    recovered = alexa.AlexaBridge(hass)
    await recovered.load()
    assert recovered.settings["account"]["devices"] == original_mapping
    assert recovered.pairing_choices("account") == choices


async def test_concurrent_account_setup_registers_one_view_and_keeps_both_accounts(chat):  # noqa: F811
    hass, _, entry, _, _ = chat
    hass.http = SimpleNamespace(register_view=Mock())
    second = SimpleNamespace(entry_id="second-account")
    await asyncio.gather(alexa.async_setup_alexa(hass, entry), alexa.async_setup_alexa(hass, second))
    assert set(hass.data[alexa.KEY].entries) == {"account", "second-account"}
    hass.http.register_view.assert_called_once()


async def test_alexa_options_are_admin_only_and_do_not_change_model_options(bridge, monkeypatch):
    manager, hass, _, entry, users, _, _, target = bridge
    hass.data[alexa.KEY] = manager
    for user in users.values():
        user.name = user.id
    hass.auth.async_get_users = AsyncMock(return_value=list(users.values()))
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    original_options = copy.deepcopy(entry.options)
    form = await flow.async_step_alexa()
    assert form["step_id"] == "alexa"
    values = {"enabled": True, "skill_id": TEST_SKILL_ID, "user_id": "one", "limit": 400}
    token = current_request.set({"hass_user": users["one"]})
    try:
        assert (await flow.async_step_alexa(values))["reason"] == "alexa_admin_required"
    finally:
        current_request.reset(token)
    token = current_request.set({"hass_user": users["admin"]})
    try:
        result = await flow.async_step_alexa(
            {
                **values,
                "device": next(iter(manager.pending)),
                "target": target,
            }
        )
        assert result["reason"] == "alexa_saved"
        assert manager.settings["account"]["limit"] == 400
        assert entry.options == original_options
    finally:
        current_request.reset(token)


def test_spoken_budget_and_no_ssml_or_markdown():
    spoken = alexa.spoken_text("<speak>Hi</speak> **temperature** [source](https://example.com) " * 100, 450)
    assert len(spoken) <= 450
    assert "<" not in spoken and "**" not in spoken and "https://" not in spoken
    assert spoken.endswith("The full answer is in ChatGPT Assist.")


@pytest.mark.parametrize(
    "url",
    [
        "http://s3.amazonaws.com/echo.api/cert.pem",
        "https://evil.test/echo.api/cert.pem",
        "https://s3.amazonaws.com/echo.api/../../secret.pem",
        "https://s3.amazonaws.com:8443/echo.api/cert.pem",
        "https://name@s3.amazonaws.com/echo.api/cert.pem",
        "https://s3.amazonaws.com/echo.api/%2e%2e/cert.pem",
        "https://s3.amazonaws.com/echo.api/cert.pem?redirect=evil",
    ],
)
def test_certificate_url_ssrf_rejections(url):
    with pytest.raises(alexa_security.AlexaSecurityError):
        alexa_security.certificate_url(url)


@pytest.mark.parametrize("offset", [-151, 151])
def test_old_and_future_timestamp_rejected(offset):
    data = envelope()
    data["request"]["timestamp"] = (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()
    with pytest.raises(alexa_security.AlexaSecurityError):
        alexa_security.timestamp_valid(data)


@pytest.fixture
def signing_chain(monkeypatch):
    now = datetime.now(UTC)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test root")])

    def builder(subject, issuer, key):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
        )

    root = (
        builder(root_name, root_name, root_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), False)
        .sign(root_key, hashes.SHA256())
    )
    leaf = (
        builder(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Alexa")]), root_name, leaf_key)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("echo-api.amazon.com")]), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), False)
        .sign(root_key, hashes.SHA256())
    )
    monkeypatch.setattr(
        alexa_security.ssl,
        "create_default_context",
        lambda: SimpleNamespace(get_ca_certs=lambda binary: [root.public_bytes(serialization.Encoding.DER)]),
    )
    return (
        leaf_key,
        leaf,
        leaf.public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM),
    )


def test_real_certificate_chain_and_signature(signing_chain, monkeypatch):
    key, leaf, pem = signing_chain
    assert alexa_security.trusted_signer(pem) == leaf
    body = json.dumps(envelope()).encode()
    signature = base64.b64encode(key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
    alexa_security.verify_signature(leaf, signature, body)
    monkeypatch.setattr(
        alexa_security.ssl, "create_default_context", lambda: SimpleNamespace(get_ca_certs=lambda binary: [])
    )
    with pytest.raises(alexa_security.AlexaSecurityError):
        alexa_security.verify_signature(leaf, signature, body + b" ")
    with pytest.raises(alexa_security.AlexaSecurityError):
        alexa_security.trusted_signer(leaf.public_bytes(serialization.Encoding.PEM))


async def test_http_rejects_unsigned_tampered_and_oversized_before_dispatch(bridge, signing_chain):
    manager, _, _, _, _, calls, _, _ = bridge
    key, leaf, _ = signing_chain
    url = "https://s3.amazonaws.com/echo.api/test.pem"
    import time

    manager.certificates[url] = (time.monotonic(), leaf)
    app = web.Application()
    app.router.add_post(alexa.URL, alexa.AlexaView(manager).post)
    async with TestClient(TestServer(app)) as client:
        body = json.dumps(envelope()).encode()
        assert (await client.post(alexa.URL, data=body)).status == 400
        signature = base64.b64encode(key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
        headers = {"SignatureCertChainUrl": url, "Signature-256": signature}
        assert (await client.post(alexa.URL, data=body + b" ", headers=headers)).status == 400
        assert (await client.post(alexa.URL, data=b"x" * 32769, headers=headers)).status == 413
        assert not calls
        response = await client.post(alexa.URL, data=body, headers=headers)
        assert response.status == 200
        assert (await response.json())["response"]["shouldEndSession"] is True
        await finish(manager)
        assert len(calls) == 1
