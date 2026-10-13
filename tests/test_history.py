"""Recorder reads, permissions, bounded results and history-only conversations."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

from custom_components.chatgpt_assist import history
from custom_components.chatgpt_assist.administration import ConfigurationAPI
from custom_components.chatgpt_assist.compat import schema_to_json
from custom_components.chatgpt_assist.config_flow import ChatGPTOptionsFlow
from custom_components.chatgpt_assist.conversation import ChatGPTConversation


@pytest.fixture
async def environment(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    user = SimpleNamespace(
        is_active=True,
        system_generated=False,
        permissions=SimpleNamespace(check_entity=Mock(return_value=True)),
    )
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    hass.states.async_set(
        "sensor.temperature",
        "21",
        {"friendly_name": "Bedroom", "unit_of_measurement": "°C", "state_class": "measurement"},
    )
    hass.states.async_set("sensor.private", "99", {"friendly_name": "Private"})
    entry = SimpleNamespace(
        entry_id="test",
        options={"history_access": True, "history_entity_ids": ["sensor.temperature"], "model": "test"},
    )
    recorder = SimpleNamespace(async_add_executor_job=AsyncMock(return_value={}))
    monkeypatch.setattr(history, "get_instance", lambda hass: recorder)
    monkeypatch.setattr(
        history,
        "async_list_statistic_ids",
        AsyncMock(return_value=[{"statistic_id": "sensor.temperature", "display_unit_of_measurement": "°C"}]),
    )
    yield hass, entry, history.HistoryAccess(hass, entry), user, recorder
    await hass.async_stop()


def interval(days=1):
    end = dt_util.utcnow() - timedelta(hours=1)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


async def test_list_only_explicit_grants_and_actor_permissions(environment):
    _, entry, access, user, _ = environment
    result = await access.list("user")
    assert result["entity_ids"] == ["sensor.temperature"]
    assert result["entities"][0]["name"] == "Bedroom"
    assert "private" not in str(result)
    user.permissions.check_entity.return_value = False
    assert (await access.list("user"))["entities"] == []
    entry.options["history_access"] = False
    with pytest.raises(history.HistoryError, match="disabled"):
        await access.list("user")


@pytest.mark.parametrize("actor", [None, "inactive", "system"])
async def test_untrusted_actor_rejected_before_recorder(environment, actor):
    _, _, access, user, recorder = environment
    user.is_active = actor != "inactive"
    user.system_generated = actor == "system"
    with pytest.raises(history.HistoryError, match="authenticated"):
        await access.read(actor, "sensor.temperature", *interval(), "raw")
    recorder.async_add_executor_job.assert_not_called()


@pytest.mark.parametrize("entity", ["sensor.private", "sensor.*", "external:meter", "light.kitchen"])
async def test_ungranted_entity_rejected_before_query(environment, entity):
    _, _, access, _, recorder = environment
    with pytest.raises(history.HistoryError, match="not granted"):
        await access.read("user", entity, *interval(), "raw")
    recorder.async_add_executor_job.assert_not_called()


@pytest.mark.parametrize(
    ("start", "end", "resolution"),
    [
        ("2026-01-01", "2026-01-02", "raw"),
        ("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z", "raw"),
        ("2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z", "hour"),
        ("2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "day"),
        ("2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z", "day"),
        ("bad", "bad", "day"),
        ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "sql"),
        ("2099-01-01T00:00:00Z", "2099-01-02T00:00:00Z", "day"),
    ],
)
async def test_invalid_or_excessive_intervals_do_not_query(environment, start, end, resolution):
    _, _, access, _, recorder = environment
    with pytest.raises(history.HistoryError):
        await access.read("user", "sensor.temperature", start, end, resolution)
    recorder.async_add_executor_job.assert_not_called()


async def test_raw_history_chunks_filters_attributes_and_marks_truncation(environment):
    _, _, access, _, recorder = environment
    recorder.async_add_executor_job.return_value = {
        "sensor.temperature": [
            State("sensor.temperature", "21", {"secret": "DO_NOT_SEND"}) for _ in range(601)
        ]
    }
    result = await access.read("user", "sensor.temperature", *interval(), "raw")
    assert result["returned_points"] == 600 and result["truncated"] is True
    assert "DO_NOT_SEND" not in str(result)
    query = recorder.async_add_executor_job.call_args.args[0]
    assert query.func is history.get_significant_states
    assert query.args[-1] == ["sensor.temperature"]
    assert query.args[2] - query.args[1] == timedelta(hours=1)
    assert query.keywords["no_attributes"] is True


async def test_statistics_metadata_units_finite_fields_and_missing_data(environment):
    _, _, access, _, recorder = environment
    timestamp = (dt_util.utcnow() - timedelta(days=1)).timestamp()
    recorder.async_add_executor_job.return_value = {
        "sensor.temperature": [
            {
                "start": timestamp,
                "end": timestamp + 3600,
                "mean": 20.5,
                "min": 18,
                "max": 23,
                "sum": float("nan"),
                "secret": "DO_NOT_SEND",
            }
        ]
    }
    result = await access.read("user", "sensor.temperature", *interval(), "hour")
    assert result["points"][0]["mean"] == 20.5
    assert result["unit"] == "°C" and result["empty"] is False
    assert "sum" not in result["points"][0] and "secret" not in str(result)
    args = recorder.async_add_executor_job.call_args.args
    assert args[0] is history.statistics_during_period and args[4] == {"sensor.temperature"}
    recorder.async_add_executor_job.return_value = {}
    empty = await access.read("user", "sensor.temperature", *interval(), "day")
    assert empty["points"] == [] and empty["empty"] is True


async def test_permission_revocation_while_reading_blocks_result(environment):
    _, _, access, user, recorder = environment

    async def revoke(*args):
        user.permissions.check_entity.return_value = False
        return {"sensor.temperature": []}

    recorder.async_add_executor_job.side_effect = revoke
    with pytest.raises(history.HistoryError, match="not granted"):
        await access.read("user", "sensor.temperature", *interval(), "hour")


async def test_history_only_api_has_no_configuration_or_control_tools(environment):
    hass, entry, _, _, _ = environment
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="user"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    instance = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert {tool.name for tool in instance.tools} == {"history_list", "history_read"}
    for tool in instance.tools:
        schema_to_json(tool.parameters)
    entry.options["history_access"] = False
    instance = await ConfigurationAPI(hass, entry).async_get_api_instance(context)
    assert instance.tools == []


async def test_history_checklist_bulk_review_preserves_grants(environment, monkeypatch):
    from custom_components.chatgpt_assist import config_flow

    hass, entry, _, _, _ = environment
    entry.runtime_data = SimpleNamespace(
        administration=SimpleNamespace(
            choices=AsyncMock(return_value=({"automation": [], "dashboard": []}, ""))
        ),
        access_token=AsyncMock(return_value="fake"),
    )
    monkeypatch.setattr(ChatGPTOptionsFlow, "config_entry", property(lambda self: entry))
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(
        config_flow, "available_models", AsyncMock(return_value=[{"value": "test", "label": "Test"}])
    )
    flow = ChatGPTOptionsFlow()
    flow.hass = hass
    form = await flow.async_step_settings()
    assert form["data_schema"]({})["history_entity_ids"] == ["sensor.temperature"]
    result = await flow.async_step_settings(form["data_schema"]({"select_all_history": True}))
    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested["history_entity_ids"] == ["sensor.private", "sensor.temperature"]
    assert entry.options["history_entity_ids"] == ["sensor.temperature"]
    saved = await flow.async_step_settings(result["data_schema"](suggested))
    assert saved["data"]["history_entity_ids"] == ["sensor.private", "sensor.temperature"]
    result = await flow.async_step_settings(form["data_schema"]({"select_none_history": True}))
    key = next(key for key in result["data_schema"].schema if key.schema == "history_entity_ids")
    assert key.description["suggested_value"] == []


async def test_revoked_old_history_stops_before_provider(environment, monkeypatch):
    from custom_components.chatgpt_assist import conversation as agent

    hass, entry, _, _, _ = environment
    entity = ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.chatgpt"
    user = conversation.ConversationInput(
        text="What was it yesterday?",
        context=Context(user_id="user"),
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
            tool_name="history_read",
            **(
                {"result": llm.ToolResult(data={"entity_ids": ["sensor.private"], "points": []})}
                if hasattr(llm, "ToolResult")
                else {"tool_result": {"entity_ids": ["sensor.private"], "points": []}}
            ),
        )
    )
    response = AsyncMock()
    monkeypatch.setattr(agent, "response", response)
    result = await entity._async_handle_message(user, log)
    assert result.response.response_type.value == "error"
    response.assert_not_called()


async def test_real_recorder_raw_states_and_hourly_statistics(tmp_path):
    """Exercise Core's SQLite Recorder rather than assuming its return shape."""
    from homeassistant import loader
    from homeassistant.auth import auth_manager_from_config
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_import_statistics
    from homeassistant.components.recorder.tasks import SynchronizeTask
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.helpers import area_registry, device_registry, entity_registry
    from homeassistant.helpers.recorder import async_initialize_recorder
    from homeassistant.setup import async_setup_component

    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    if hasattr(device_registry, "async_setup"):
        device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    await area_registry.async_load(hass)
    hass.auth = await auth_manager_from_config(hass, [], [])
    user = await hass.auth.async_create_user("History test administrator")
    async_initialize_recorder(hass)
    try:
        assert await async_setup_component(
            hass,
            "recorder",
            {"recorder": {"db_url": f"sqlite:///{tmp_path / 'history.db'}", "commit_interval": 0}},
        )
        await hass.async_start()
        recorder = get_instance(hass)
        start = dt_util.utcnow() - timedelta(minutes=1)
        hass.states.async_set(
            "sensor.temperature", "21", {"unit_of_measurement": "°C", "secret": "DO_NOT_SEND"}
        )
        await hass.async_block_till_done()
        await recorder.async_block_till_done()
        entry = SimpleNamespace(
            options={"history_access": True, "history_entity_ids": ["sensor.temperature"]}
        )
        access = history.HistoryAccess(hass, entry)
        raw = await access.read(
            user.id, "sensor.temperature", start.isoformat(), dt_util.utcnow().isoformat(), "raw"
        )
        assert raw["points"] and raw["points"][-1]["state"] == "21"
        assert "DO_NOT_SEND" not in str(raw)
        bucket = (dt_util.utcnow() - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        async_import_statistics(
            hass,
            {
                "statistic_id": "sensor.temperature",
                "source": "recorder",
                "name": "Temperature",
                "unit_of_measurement": "°C",
                "unit_class": "temperature",
                "mean_type": StatisticMeanType.ARITHMETIC,
                "has_sum": False,
            },
            [{"start": bucket, "mean": 20, "min": 18, "max": 22}],
        )
        committed = hass.loop.create_future()
        recorder.queue_task(SynchronizeTask(committed))
        await committed
        result = await access.read(
            user.id,
            "sensor.temperature",
            bucket.isoformat(),
            (bucket + timedelta(hours=1)).isoformat(),
            "hour",
        )
        assert result["points"][0]["mean"] == 20
        assert result["points"][0]["min"] == 18 and result["points"][0]["max"] == 22
        assert result["unit"] == "°C"
        # Display units come from Recorder conversion, not an assumed database unit.
        hass.states.async_set("sensor.temperature", "69.8", {"unit_of_measurement": "°F"})
        converted = await access.read(
            user.id,
            "sensor.temperature",
            bucket.isoformat(),
            (bucket + timedelta(hours=1)).isoformat(),
            "hour",
        )
        assert converted["unit"] == "°F" and converted["points"][0]["mean"] == 68
        day_start = bucket.replace(hour=0)
        daily = await access.read(
            user.id,
            "sensor.temperature",
            day_start.isoformat(),
            (day_start + timedelta(days=1)).isoformat(),
            "day",
        )
        assert len(daily["points"]) == 1 and daily["points"][0]["mean"] == 68
    finally:
        await hass.async_stop()


async def test_history_conversation_dispatches_real_tools_and_preserves_results(environment, monkeypatch):
    import json

    from custom_components.chatgpt_assist import conversation as agent
    from custom_components.chatgpt_assist.const import NAMESPACE

    hass, entry, _, _, recorder = environment
    entry.runtime_data = SimpleNamespace(session=None, access_token=AsyncMock(return_value="fake"))
    entity = ChatGPTConversation(entry)
    entity.hass, entity.entity_id = hass, "conversation.chatgpt"
    user = conversation.ConversationInput(
        text="What was the bedroom temperature yesterday?",
        context=Context(user_id="user"),
        conversation_id="test",
        language="en",
        agent_id=entity.entity_id,
        device_id=None,
        satellite_id=None,
    )
    log = conversation.ChatLog(hass, "test")
    log.async_add_user_content(conversation.UserContent(content=user.text))

    async def provide(self, context, selected, prompt, extra):
        assert isinstance(selected, ConfigurationAPI)
        self.llm_api = await selected.async_get_api_instance(context)
        self.content[0] = conversation.SystemContent(content=prompt + self.llm_api.api_prompt)

    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", provide)
    start, end = interval()
    recorder.async_add_executor_job.return_value = {
        "sensor.temperature": [{"start": dt_util.parse_datetime(start).timestamp(), "mean": 20.5}]
    }
    responses = AsyncMock(
        side_effect=[
            {
                "output": [
                    {
                        "type": "function_call",
                        "namespace": NAMESPACE,
                        "name": "history_read",
                        "call_id": "history1",
                        "arguments": json.dumps(
                            {
                                "entity_id": "sensor.temperature",
                                "start": start,
                                "end": end,
                                "resolution": "hour",
                            }
                        ),
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "The recorded hourly average was 20.5 °C."}
                        ],
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(agent, "response", responses)
    result = await entity._async_handle_message(user, log)
    assert "20.5" in result.response.speech["plain"]["speech"]
    payload = responses.call_args.args
    json.dumps(payload[4])  # Real Core selectors must yield serializable schemas.
    assert {tool["name"] for tool in payload[4][0]["tools"]} == {"history_list", "history_read"}
    assert "20.5" in payload[3][-1]["output"]


async def test_history_list_pagination_and_missing_saved_sensor(environment):
    hass, entry, access, _, _ = environment
    for i in range(105):
        entity_id = f"sensor.probe_{i:03}"
        hass.states.async_set(entity_id, "1")
        entry.options["history_entity_ids"].append(entity_id)
    entry.options["history_entity_ids"].append("sensor.unavailable")
    first = await access.list("user")
    second = await access.list("user", first["next_offset"])
    assert len(first["entities"]) == 100 and second["next_offset"] is None
    assert len(set(first["entity_ids"] + second["entity_ids"])) == 107
    assert any(item["entity_id"] == "sensor.unavailable" for item in second["entities"])


async def test_missing_recorder_and_database_failure_are_safe_errors(environment, monkeypatch):
    hass, _, access, _, recorder = environment

    def unavailable(hass):
        raise KeyError("private internal details")

    monkeypatch.setattr(history, "get_instance", unavailable)
    tool = history.HistoryTool(access, "read")
    start, end = interval()
    context = llm.LLMContext(
        platform="chatgpt_assist",
        context=Context(user_id="user"),
        language="en",
        assistant="conversation.test",
        device_id=None,
    )
    args = llm.ToolInput(
        tool_name=tool.name,
        tool_args={"entity_id": "sensor.temperature", "start": start, "end": end, "resolution": "raw"},
    )
    result = await tool.async_call(hass, args, context)
    data = result.data if hasattr(result, "data") else result
    assert "Recorder is unavailable" in data["error"]
    assert "private" not in str(data)
    monkeypatch.setattr(history, "get_instance", lambda hass: recorder)
    recorder.async_add_executor_job.side_effect = RuntimeError("SECRET_DB_PASSWORD")
    result = await tool.async_call(hass, args, context)
    data = result.data if hasattr(result, "data") else result
    assert "could not be read" in data["error"] and "SECRET" not in str(data)


async def test_raw_byte_limit_and_boundary_chunks(environment, monkeypatch):
    _, _, access, _, recorder = environment
    monkeypatch.setattr(history, "MAX_BYTES", 1200)
    recorder.async_add_executor_job.return_value = {
        "sensor.temperature": [State("sensor.temperature", "x" * 200) for _ in range(10)]
    }
    result = await access.read("user", "sensor.temperature", *interval(), "raw")
    import json

    assert result["truncated"] is True and len(json.dumps(result).encode()) <= 1200
    monkeypatch.setattr(history, "MAX_BYTES", 96_000)
    recorder.async_add_executor_job.reset_mock()
    recorder.async_add_executor_job.return_value = {}
    await access.read("user", "sensor.temperature", *interval(), "raw")
    queries = [call.args[0] for call in recorder.async_add_executor_job.call_args_list]
    assert len(queries) == 24
    assert queries[0].keywords["include_start_time_state"] is True
    assert all(not query.keywords["include_start_time_state"] for query in queries[1:])
    assert all(a.args[2] == b.args[1] for a, b in zip(queries, queries[1:]))
