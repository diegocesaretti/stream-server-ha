"""Connectivity sensor for Stremio Stream Bridge."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StremioBridgeRuntime
from .const import (
    CONF_AUDIO_MODE,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_PLAY_IDEAL_ON_SELECT,
    DEFAULT_AUDIO_MODE,
    DEFAULT_PLAY_IDEAL_ON_SELECT,
    DOMAIN,
    PROFILE_LATIN,
    PROFILE_SPORTS,
)
from .subtitle_support import is_cast_player


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    runtime: StremioBridgeRuntime = entry.runtime_data
    async_add_entities([StremioBridgeConnectivitySensor(entry, runtime)])


class StremioBridgeConnectivitySensor(CoordinatorEntity, BinarySensorEntity):
    """Show whether stream-server and at least one add-on are reachable."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Conectividad"

    def __init__(self, entry: ConfigEntry, runtime: StremioBridgeRuntime) -> None:
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connectivity"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Stremio / Home Assistant",
            "model": "Aggregate Stream Bridge",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.coordinator.data or {}
        settings = data.get("settings", {})
        values = settings.get("values", settings) if isinstance(settings, dict) else {}
        addons = data.get("addons", [])
        errors = data.get("addon_errors", {})
        default_player = self._entry.options.get(
            CONF_DEFAULT_MEDIA_PLAYER,
            self._entry.data.get(CONF_DEFAULT_MEDIA_PLAYER),
        )
        current = {**self._entry.data, **self._entry.options}
        return {
            "server_version": values.get("serverVersion") if isinstance(values, dict) else None,
            "addons": addons,
            "addon_count": len(addons) if isinstance(addons, list) else 0,
            "addon_errors": errors,
            "subtitle_provider_errors": dict(self.coordinator.manager.last_subtitle_errors),
            "default_player": default_player,
            "external_subtitles_supported": is_cast_player(self.hass, default_player),
            "subtitle_border": "none",
            "audio_mode": current.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE),
            "direct_ideal_on_select": current.get(
                CONF_PLAY_IDEAL_ON_SELECT, DEFAULT_PLAY_IDEAL_ON_SELECT
            ),
            "latin_profile_available": self.coordinator.manager.has_profile(PROFILE_LATIN),
            "sports_profile_available": self.coordinator.manager.has_profile(PROFILE_SPORTS),
        }
