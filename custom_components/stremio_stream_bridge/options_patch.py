"""Add source-selection fields to the existing Home Assistant options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.helpers.selector import BooleanSelector, TextSelector, TextSelectorConfig

from .const import (
    CONF_HIDE_NON_LATIN_ITEMS,
    CONF_LATIN_AUDIO_KEYWORDS,
    CONF_PREFERRED_AUDIO_LANGUAGES,
    CONF_PREFER_H264,
    CONF_PREFER_SMALLER_SIZE,
    CONF_SECONDARY_STREAM_MANIFEST_URL,
    DEFAULT_HIDE_NON_LATIN_ITEMS,
    DEFAULT_LATIN_AUDIO_KEYWORDS,
    DEFAULT_PREFERRED_AUDIO_LANGUAGES,
    DEFAULT_PREFER_H264,
    DEFAULT_PREFER_SMALLER_SIZE,
    DEFAULT_SECONDARY_STREAM_MANIFEST,
)


def install_source_options_patch() -> None:
    """Append v0.5.6 fields without replacing the established config flow."""
    from .config_flow import StremioStreamBridgeOptionsFlow

    if getattr(StremioStreamBridgeOptionsFlow, "_bridge_source_options_patched", False):
        return

    original = StremioStreamBridgeOptionsFlow.async_step_init

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        result = await original(self, user_input)
        schema = result.get("data_schema") if isinstance(result, dict) else None
        if not isinstance(schema, vol.Schema):
            return result

        current = {**self.config_entry.data, **self.config_entry.options}
        displayed = {**current, **(user_input or {})}
        fields = dict(schema.schema)
        fields.update(
            {
                vol.Optional(
                    CONF_SECONDARY_STREAM_MANIFEST_URL,
                    default=str(
                        displayed.get(
                            CONF_SECONDARY_STREAM_MANIFEST_URL,
                            DEFAULT_SECONDARY_STREAM_MANIFEST,
                        )
                    ),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Required(
                    CONF_LATIN_AUDIO_KEYWORDS,
                    default=str(
                        displayed.get(
                            CONF_LATIN_AUDIO_KEYWORDS,
                            DEFAULT_LATIN_AUDIO_KEYWORDS,
                        )
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_HIDE_NON_LATIN_ITEMS,
                    default=displayed.get(
                        CONF_HIDE_NON_LATIN_ITEMS,
                        DEFAULT_HIDE_NON_LATIN_ITEMS,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_PREFERRED_AUDIO_LANGUAGES,
                    default=str(
                        displayed.get(
                            CONF_PREFERRED_AUDIO_LANGUAGES,
                            DEFAULT_PREFERRED_AUDIO_LANGUAGES,
                        )
                    ),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Required(
                    CONF_PREFER_H264,
                    default=displayed.get(CONF_PREFER_H264, DEFAULT_PREFER_H264),
                ): BooleanSelector(),
                vol.Required(
                    CONF_PREFER_SMALLER_SIZE,
                    default=displayed.get(
                        CONF_PREFER_SMALLER_SIZE,
                        DEFAULT_PREFER_SMALLER_SIZE,
                    ),
                ): BooleanSelector(),
            }
        )
        result["data_schema"] = vol.Schema(fields)
        return result

    StremioStreamBridgeOptionsFlow.async_step_init = async_step_init
    StremioStreamBridgeOptionsFlow._bridge_source_options_patched = True
