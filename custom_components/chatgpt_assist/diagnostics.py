"""Explicit diagnostics allowlist; no credentials, prompts, or entity data."""


async def async_get_config_entry_diagnostics(hass, entry):
    return {
        "integration_version": "0.1.6",
        "model": entry.options.get("model"),
        "control_enabled": entry.options.get("control", False),
        "host_id": entry.data.get("ext_agent_host_id"),
    }
