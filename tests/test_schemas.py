"""Assist's real serializer must produce JSON without unsupported sentinels."""

import json

import pytest
from homeassistant.helpers import llm
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from custom_components.chatgpt_assist.compat import schema, schema_to_json


def test_assist_serializer_with_required_and_selector_parameters():
    parameters = schema.Schema(
        {
            schema.Required("name"): str,
            schema.Optional("domain"): SelectSelector(SelectSelectorConfig(options=["light", "switch"])),
        }
    )
    converted = schema_to_json(parameters, llm.selector_serializer)
    assert converted["type"] == "object"
    assert converted["properties"]["name"]["type"] == "string"
    assert converted["properties"]["domain"]["enum"] == ["light", "switch"]
    payload = {
        "tools": [
            {
                "type": "namespace",
                "name": "home_assistant",
                "tools": [
                    {"type": "function", "name": "HassTurnOn", "parameters": converted},
                ],
            }
        ]
    }
    json.dumps(payload)
    with pytest.raises(schema.Invalid):
        parameters({"name": "Kitchen", "domain": "not-an-allowed-domain"})
