"""Native log discovery, role boundaries, redaction and bounded read-only adapters."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm
from yarl import URL

from custom_components.chatgpt_assist import logs
from custom_components.chatgpt_assist.administration import ConfigurationAPI
from custom_components.chatgpt_assist.conversation import ChatGPTConversation


@pytest.fixture
async def environment(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    users = {
        "admin": SimpleNamespace(is_admin=True, is_active=True, system_generated=False),
        "member": SimpleNamespace(is_admin=False, is_active=True, system_generated=False),
    }
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(side_effect=lambda user_id: users.get(user_id)))
    entry = SimpleNamespace(
        entry_id="test", options={"model": "test"}, data={"access_token": "PRIVATE_ACCOUNT_TOKEN_123"}
    )
    access = logs.LogsAccess(hass, entry)
    yield hass, entry, access, users
    logs.unload_logs(hass, entry.entry_id)
    await hass.async_stop()


@pytest.mark.parametrize("actor", [None, "unknown", "member"])
async def test_logs_denied_before_source_discovery(environment, actor, monkeypatch):
    _, _, access, _ = environment
    discover = AsyncMock()
    monkeypatch.setattr(access, "catalog", discover)
    with pytest.raises(logs.LogsError, match="administrator"):
        await access.sources(actor)
    discover.assert_not_called()


async def test_logs_default_native_enable_and_explicit_disable(environment):
    _, entry, access, users = environment
    result = await access.sources("admin")
    assert {"core_errors", "core_live", "activity", "trace:automation", "trace:script"} <= {
        item["source"] for item in result["sources"]
    }
    assert result["supervisor_available"] is False
    entry.options["logs_access"] = False
    with pytest.raises(logs.LogsError, match="disabled"):
        await access.sources("admin")
    entry.options["logs_access"] = True
    users["admin"].system_generated = True
    with pytest.raises(logs.LogsError):
        await access.sources("admin")


async def test_file_logs_page_search_redaction_and_no_arbitrary_paths(environment, tmp_path):
    _, _, access, _ = environment
    (tmp_path / "home-assistant.log").write_text(
        "first\nsecond\nHumidity 61\npassword=VERY_PRIVATE\nAuthorization: Bearer xyzsecret\nPRIVATE_ACCOUNT_TOKEN_123\nlast\n"
    )
    (tmp_path / "chatgpt-account.json").write_text('{"access_token": "DO_NOT_READ"}')
    sources = await access.sources("admin")
    source = next(item["source"] for item in sources["sources"] if item["name"] == "home-assistant.log")
    result = await access.read("admin", source, lines=3)
    assert "last" in result["text"] and "PRIVATE_ACCOUNT_TOKEN" not in result["text"]
    result = await access.read("admin", source, lines=500)
    assert "VERY_PRIVATE" not in result["text"] and "xyzsecret" not in result["text"]
    assert "[REDACTED]" in result["text"]
    filtered = await access.read("admin", source, search="humidity")
    assert filtered["text"] == "Humidity 61"
    page = await access.read("admin", source, lines=2, offset=5)
    assert page["text"] == "first\nsecond"
    with pytest.raises(logs.LogsError, match="unavailable"):
        await access.read("admin", "../../chatgpt-account.json")


async def test_native_file_discovery_rejects_symlink_and_bounded_tail(environment, tmp_path, monkeypatch):
    _, _, access, _ = environment
    secret = tmp_path / "secret.json"
    secret.write_text("DO_NOT_READ")
    (tmp_path / "linked.log").symlink_to(secret)
    (tmp_path / "large.log").write_text("old\n" * 100 + "recent\n" * 100)
    monkeypatch.setattr(logs, "MAX_SCAN", 100)
    monkeypatch.setattr(logs, "MAX_OUTPUT", 30)
    catalog = await access.catalog()
    assert not any(item["name"] == "linked.log" for item in catalog.values())
    source = next(key for key, item in catalog.items() if item["name"] == "large.log")
    result = await access.read("admin", source, lines=500)
    assert result["truncated"] is True and len(result["text"].encode()) <= 30
    assert "old" not in result["text"]


async def test_core_condensed_and_live_buffer_are_native_and_bounded(environment, monkeypatch):
    hass, entry, access, _ = environment
    hass.data["system_log"] = SimpleNamespace(
        records=SimpleNamespace(to_list=lambda: [{"message": "api_key=PRIVATE_KEY", "level": "ERROR"}])
    )
    result = await access.read("admin", "core_errors")
    assert "PRIVATE_KEY" not in result["text"] and "ERROR" in result["text"]
    logs.setup_logs(hass, entry)
    logs.setup_logs(hass, entry)
    logger = logging.getLogger("test_native_ha_logs")
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info("native activity Authorization: Bearer secret123")
    finally:
        logger.setLevel(old_level)
    result = await access.read("admin", "core_live")
    assert "native activity" in result["text"] and "secret123" not in result["text"]
    assert logging.getLogger().handlers.count(hass.data[logs.BUFFER_KEY]) == 1
    monkeypatch.setattr(logs, "MAX_SCAN", 100)
    for index in range(100):
        hass.data[logs.BUFFER_KEY].emit(
            logging.LogRecord("test", logging.WARNING, "test", 1, str(index) * 10, (), None)
        )
    assert hass.data[logs.BUFFER_KEY].bytes <= 100
    logs.unload_logs(hass, entry.entry_id)
    assert logs.BUFFER_KEY not in hass.data


class Content:
    def __init__(self, data):
        self.data = data

    async def iter_chunked(self, size):
        for index in range(0, len(self.data), size):
            yield self.data[index : index + size]


class Response:
    def __init__(self, data, status=200):
        self.status = status
        self.content = Content(data if isinstance(data, bytes) else data.encode())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class SupervisorSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        responses = {
            "/addons": {
                "addons": [{"slug": "core_mosquitto", "name": "MQTT"}, {"slug": "../evil", "name": "Bad"}]
            },
            "/host/logs/identifiers": ["NetworkManager", "kernel", "unsafe/../identifier"],
            "/host/logs/boots": {"0": "current", "-1": "previous"},
        }
        if url.path in responses:
            return Response(json.dumps({"result": "ok", "data": responses[url.path]}))
        return Response("startup\nAuthorization: Bearer SUPERVISOR_PRIVATE\nMQTT connection failed\n")


async def test_supervisor_apps_plugins_host_identifiers_and_boots_are_discovered(environment, monkeypatch):
    hass, _, access, _ = environment
    session = SupervisorSession()
    hass.data["hassio"] = SimpleNamespace(base_url=URL("http://supervisor"), websession=session)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "NATIVE_SUPERVISOR_TOKEN_123")
    result = await access.sources("admin")
    sources = {item["source"]: item for item in result["sources"]}
    assert {
        "supervisor:core",
        "supervisor:supervisor",
        "supervisor:host",
        "supervisor:dns",
        "supervisor:audio",
        "supervisor:cli",
        "supervisor:multicast",
        "supervisor:observer",
        "app:core_mosquitto",
    } <= sources.keys()
    assert "app:../evil" not in sources
    read = await access.read("admin", "app:core_mosquitto", boot=-1)
    assert "connection failed" in read["text"] and "SUPERVISOR_PRIVATE" not in read["text"]
    assert session.calls[-1][0].path == "/addons/core_mosquitto/logs/boots/-1"
    assert session.calls[-1][1]["headers"]["Authorization"] == "Bearer NATIVE_SUPERVISOR_TOKEN_123"
    assert session.calls[-1][1]["allow_redirects"] is False
    journal = next(item for item in result["sources"] if "unsafe/../identifier" in item["name"])
    await access.read("admin", journal["source"])
    assert session.calls[-1][0].path == "/host/logs"
    assert session.calls[-1][1]["params"]["identifier"] == "unsafe/../identifier"


async def test_supervisor_credentials_not_present_does_not_contact_network(environment):
    hass, _, access, _ = environment
    session = SupervisorSession()
    hass.data["hassio"] = SimpleNamespace(base_url=URL("http://supervisor"), websession=session)
    with pytest.raises(logs.LogsError, match="authentication"):
        await access._supervisor("/core/logs")
    assert session.calls == []


async def test_permissions_rechecked_after_log_read(environment, monkeypatch):
    hass, _, access, users = environment
    monkeypatch.setattr(
        access, "catalog", AsyncMock(return_value={"test": {"kind": "supervisor", "endpoint": "/core/logs"}})
    )

    async def read(*args, **kwargs):
        users["admin"].is_admin = False
        return "private logs", False

    monkeypatch.setattr(access, "_supervisor", read)
    with pytest.raises(logs.LogsError, match="administrator"):
        await access.read("admin", "test")


async def test_logs_only_api_and_revoked_history_do_not_reach_provider(environment, monkeypatch):
    from custom_components.chatgpt_assist import conversation as agent

    hass, entry, _, users = environment
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="admin"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    instance = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert {tool.name for tool in instance.tools} == {"logs_sources", "logs_read"}
    users["admin"].is_admin = False
    instance = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert instance.tools == []
    entity = ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.test"
    user = conversation.ConversationInput(
        text="Continue",
        context=Context(user_id="admin"),
        conversation_id="test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "test")
    log.content.append(
        conversation.ToolResultContent(
            agent_id=entity.entity_id,
            tool_call_id="old",
            tool_name="logs_read",
            **(
                {"result": llm.ToolResult(data={"text": "private log"})}
                if hasattr(llm, "ToolResult")
                else {"tool_result": {"text": "private log"}}
            ),
        )
    )
    provider = AsyncMock()
    monkeypatch.setattr(agent, "response", provider)
    result = await entity._async_handle_message(user, log)
    assert result.response.response_type.value == "error"
    provider.assert_not_called()


def test_common_credentials_redacted_but_useful_diagnostics_remain():
    text = 'MQTT failed password="secretpass" api_key=PRIVATE_KEY https://user:password@host/\nCookie: session=secret\n-----BEGIN PRIVATE KEY-----\nPRIVATE_CONTENT\n-----END PRIVATE KEY-----'
    result = logs.redact(text)
    for value in ("secretpass", "PRIVATE_KEY", "user:password", "session=secret", "PRIVATE_CONTENT"):
        assert value not in result
    assert "MQTT failed" in result and "[REDACTED]" in result


async def test_activity_adapter_uses_native_processor_and_explicit_interval(environment, monkeypatch):
    from datetime import timedelta

    from homeassistant.components import recorder
    from homeassistant.components.logbook import helpers, processor
    from homeassistant.util import dt as dt_util

    hass, _, access, _ = environment
    hass.data["logbook"] = {}
    seen = []

    class Processor:
        def __init__(self, hass, types, **kwargs):
            seen.append(types)

        def get_events(self, start, end):
            seen.append((start, end))
            return [{"name": "Humidity automation", "message": "triggered", "password": "SECRET_ACTIVITY"}]

    async def execute(function, *args):
        return function(*args)

    monkeypatch.setattr(helpers, "async_determine_event_types", lambda *args: {"automation_triggered"})
    monkeypatch.setattr(processor, "EventProcessor", Processor)
    monkeypatch.setattr(
        recorder, "get_instance", lambda hass: SimpleNamespace(async_add_executor_job=execute)
    )
    result = await access.read("admin", "activity")
    assert "Humidity automation" in result["text"] and "SECRET_ACTIVITY" not in result["text"]
    assert seen[1][1] - seen[1][0] == timedelta(hours=1)
    with pytest.raises(logs.LogsError, match="24 hours"):
        await access.read("admin", "activity", start=(dt_util.utcnow() - timedelta(days=2)).isoformat())


async def test_trace_summaries_and_details_use_native_trace_api(environment, monkeypatch):
    from homeassistant.components.trace import util

    hass, _, access, _ = environment
    hass.data["trace"] = {}
    listed = AsyncMock(return_value=[{"run_id": "run1", "item_id": "morning", "state": "stopped"}])
    detailed = AsyncMock(
        return_value={"error": "condition failed", "variables": {"password": "SECRET_TRACE"}}
    )
    monkeypatch.setattr(util, "async_list_traces", listed)
    monkeypatch.setattr(util, "async_get_trace", detailed)
    result = await access.read("admin", "trace:automation", item_id="morning")
    listed.assert_awaited_once_with(hass, "automation", "automation.morning")
    assert "run1" in result["text"]
    result = await access.read("admin", "trace:automation", item_id="morning", run_id="run1")
    detailed.assert_awaited_once_with(hass, "automation.morning", "run1")
    assert "condition failed" in result["text"] and "SECRET_TRACE" not in result["text"]
    with pytest.raises(logs.LogsError):
        await access.read("admin", "trace:automation", run_id="run1")


async def test_known_credentials_from_other_integration_accounts_are_redacted(environment, tmp_path):
    hass, _, access, _ = environment
    other = SimpleNamespace(
        data={"refresh_token": "OTHER_ACCOUNT_PRIVATE_TOKEN"},
        runtime_data=SimpleNamespace(tokens={"access_token": "ROTATED_ACCOUNT_PRIVATE_TOKEN"}),
    )
    hass.config_entries = SimpleNamespace(async_entries=lambda domain: [other])
    (tmp_path / "home-assistant.log").write_text(
        "OTHER_ACCOUNT_PRIVATE_TOKEN\nROTATED_ACCOUNT_PRIVATE_TOKEN\nnormal diagnostic"
    )
    source = next(
        item["source"]
        for item in (await access.sources("admin"))["sources"]
        if item["name"] == "home-assistant.log"
    )
    result = await access.read("admin", source)
    assert "PRIVATE_TOKEN" not in result["text"] and "normal diagnostic" in result["text"]
