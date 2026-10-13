"""Helpers for submitting and inspecting real nested Home Assistant forms."""

from homeassistant.data_entry_flow import section

from custom_components.chatgpt_assist.config_flow import _flatten_settings, _group_settings


def validate_settings(form, values):
    return _flatten_settings(form["data_schema"](_group_settings(values)))


def settings_fields(form):
    fields = {}
    for key, value in form["data_schema"].schema.items():
        if isinstance(value, section):
            fields.update(value.schema.schema)
        else:
            fields[key] = value
    return fields


def suggested_settings(form):
    return {
        key.schema: key.description["suggested_value"]
        for key in settings_fields(form)
        if key.description and "suggested_value" in key.description
    }
