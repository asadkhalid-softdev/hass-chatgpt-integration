"""Use the schema implementation used by Home Assistant's built-in LLM tools."""

from homeassistant.helpers import llm

__all__ = ["schema", "schema_to_json"]

# Other custom integrations may install both libraries. Match Core's tools rather
# than selecting whichever library happens to be importable.
if type(llm.Tool.parameters).__module__.split(".")[0] == "probatio":
    import probatio as schema
    from probatio import to_openapi

    def schema_to_json(parameters, custom_serializer=None):
        """Handle probatio's UNSUPPORTED sentinel using its matching converter."""
        return to_openapi(parameters, custom_serializer=custom_serializer, openapi_version="3.1.0")
else:
    import voluptuous as schema
    from voluptuous_openapi import convert

    def schema_to_json(parameters, custom_serializer=None):
        """Convert legacy Core schemas using voluptuous-openapi."""
        return convert(parameters, custom_serializer=custom_serializer)
