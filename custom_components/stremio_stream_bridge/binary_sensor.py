"""Connectivity and linked-account sensors for Stremio Stream Bridge."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StremioBridgeRuntime
from .account_bridge import (
    StremioAccountRuntime,
    async_install_account_bridge,
    remove_account_runtime,
)
from .account_media_patch import install_account_media_patch
from .account_options_patch import install_account_options_patch
from .account_playback_tracker import StremioAccountPlaybackTracker
from .const import (
    CONF_ACCOUNT_ENABLED,
    CONF_ACCOUNT_PROVIDER_MODE,
    CONF_AUDIO_MODE,
    CONF_CAST_COMPATIBILITY_FILTER,
    CONF_CAST_RESET_BEFORE_PLAY,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_FAILURE_NOTIFY_HA,
    CONF_FALLBACK_ENABLED,
    CONF_FALLBACK_SOURCE_COUNT,
    CONF_HIDE_NON_LATIN_ITEMS,
    CONF_LATIN_AUDIO_KEYWORDS,
    CONF_PLAYBACK_START_TIMEOUT,
    CONF_PLAY_IDEAL_ON_SELECT,
    CONF_PREFERRED_AUDIO_LANGUAGES,
    CONF_PREFER_H264,
    CONF_PREFER_SMALLER_SIZE,
    CONF_SECONDARY_STREAM_MANIFEST_URL,
    CONF_STOP_BEFORE_PLAY,
    DEFAULT_ACCOUNT_ENABLED,
    DEFAULT_ACCOUNT_PROVIDER_MODE,
    DEFAULT_AUDIO_MODE,
    DEFAULT_CAST_COMPATIBILITY_FILTER,
    DEFAULT_CAST_RESET_BEFORE_PLAY,
    DEFAULT_FAILURE_NOTIFY_HA,
    DEFAULT_FALLBACK_ENABLED,
    DEFAULT_FALLBACK_SOURCE_COUNT,
    DEFAULT_HIDE_NON_LATIN_ITEMS,
    DEFAULT_LATIN_AUDIO_KEYWORDS,
    DEFAULT_PLAYBACK_START_TIMEOUT,
    DEFAULT_PLAY_IDEAL_ON_SELECT,
    DEFAULT_PREFERRED_AUDIO_LANGUAGES,
    DEFAULT_PREFER_H264,
    DEFAULT_PREFER_SMALLER_SIZE,
    DEFAULT_SECONDARY_STREAM_MANIFEST,
    DEFAULT_STOP_BEFORE_PLAY,
    DOMAIN,
    PROFILE_LATIN,
    PROFILE_SPORTS,
)
from .latin_fallback import install_latin_stream_fallback
from .latin_search_patch import install_latin_media_search_patch
from .options_patch import install_source_options_patch
from .secondary_provider import install_secondary_stream_provider
from .server_preferences import install_preferred_audio_languages
from .source_preferences import install_source_preferences
from .subtitle_support import is_cast_player


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up connectivity plus optional Stremio account support."""
    install_source_options_patch()
    install_account_options_patch()
    install_latin_media_search_patch()
    install_account_media_patch()

    runtime: StremioBridgeRuntime = entry.runtime_data
    current = {**entry.data, **entry.options}
    await install_secondary_stream_provider(
        runtime.manager,
        async_get_clientsession(hass),
        current.get(
            CONF_SECONDARY_STREAM_MANIFEST_URL,
            DEFAULT_SECONDARY_STREAM_MANIFEST,
        ),
    )
    account_runtime = await async_install_account_bridge(hass, entry, runtime)

    install_source_preferences(
        runtime.manager,
        prefer_h264=bool(current.get(CONF_PREFER_H264, DEFAULT_PREFER_H264)),
        prefer_smaller_size=bool(
            current.get(CONF_PREFER_SMALLER_SIZE, DEFAULT_PREFER_SMALLER_SIZE)
        ),
        latin_audio_keywords=current.get(
            CONF_LATIN_AUDIO_KEYWORDS, DEFAULT_LATIN_AUDIO_KEYWORDS
        ),
        hide_non_latin_items=bool(
            current.get(CONF_HIDE_NON_LATIN_ITEMS, DEFAULT_HIDE_NON_LATIN_ITEMS)
        ),
        force_transcode=current.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE)
        == "force_transcode",
    )
    install_latin_stream_fallback(runtime.manager)
    install_preferred_audio_languages(
        runtime.server,
        current.get(
            CONF_PREFERRED_AUDIO_LANGUAGES,
            DEFAULT_PREFERRED_AUDIO_LANGUAGES,
        ),
    )

    entities: list[BinarySensorEntity] = [
        StremioBridgeConnectivitySensor(entry, runtime)
    ]
    if account_runtime is not None:
        account_runtime.tracker = StremioAccountPlaybackTracker(
            hass, entry, account_runtime
        )
        entities.append(StremioAccountLinkedSensor(entry, account_runtime))
    async_add_entities(entities)


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
        diagnostics = data.get("casting_diagnostics", {})
        if not isinstance(diagnostics, dict):
            diagnostics = {}
        addons = data.get("addons", [])
        errors = data.get("addon_errors", {})
        default_player = self._entry.options.get(
            CONF_DEFAULT_MEDIA_PLAYER,
            self._entry.data.get(CONF_DEFAULT_MEDIA_PLAYER),
        )
        current = {**self._entry.data, **self._entry.options}
        return {
            "server_version": values.get("serverVersion")
            if isinstance(values, dict)
            else None,
            "cast_diagnostics_available": diagnostics.get("available", False),
            "cast_selected_encoder": diagnostics.get("selected_encoder"),
            "cast_nvenc_usable": diagnostics.get("nvenc_usable"),
            "cast_hardware_ready": diagnostics.get("hardware_ready", False),
            "cast_diagnostics_reason": diagnostics.get("reason"),
            "hls_hardware_log_expected": (
                'HLS transcoder selected ... encoder="h264_nvenc" hardware=true'
            ),
            "addons": addons,
            "addon_count": len(addons) if isinstance(addons, list) else 0,
            "addon_errors": errors,
            "subtitle_provider_errors": dict(
                self.coordinator.manager.last_subtitle_errors
            ),
            "default_player": default_player,
            "external_subtitles_supported": is_cast_player(self.hass, default_player),
            "subtitle_border": "none",
            "audio_mode": current.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE),
            "secondary_stream_manifest_url": current.get(
                CONF_SECONDARY_STREAM_MANIFEST_URL,
                DEFAULT_SECONDARY_STREAM_MANIFEST,
            ),
            "cast_compatibility_filter": current.get(
                CONF_CAST_COMPATIBILITY_FILTER, DEFAULT_CAST_COMPATIBILITY_FILTER
            ),
            "prefer_h264": current.get(CONF_PREFER_H264, DEFAULT_PREFER_H264),
            "prefer_smaller_size": current.get(
                CONF_PREFER_SMALLER_SIZE, DEFAULT_PREFER_SMALLER_SIZE
            ),
            "spanish_audio_keywords": current.get(
                CONF_LATIN_AUDIO_KEYWORDS, DEFAULT_LATIN_AUDIO_KEYWORDS
            ),
            "preferred_audio_languages": current.get(
                CONF_PREFERRED_AUDIO_LANGUAGES,
                DEFAULT_PREFERRED_AUDIO_LANGUAGES,
            ),
            "hide_without_spanish_audio": current.get(
                CONF_HIDE_NON_LATIN_ITEMS, DEFAULT_HIDE_NON_LATIN_ITEMS
            ),
            "stop_before_play": current.get(
                CONF_STOP_BEFORE_PLAY, DEFAULT_STOP_BEFORE_PLAY
            ),
            "cast_reset_before_play": current.get(
                CONF_CAST_RESET_BEFORE_PLAY, DEFAULT_CAST_RESET_BEFORE_PLAY
            ),
            "fallback_enabled": current.get(
                CONF_FALLBACK_ENABLED, DEFAULT_FALLBACK_ENABLED
            ),
            "fallback_source_count": current.get(
                CONF_FALLBACK_SOURCE_COUNT, DEFAULT_FALLBACK_SOURCE_COUNT
            ),
            "playback_start_timeout": current.get(
                CONF_PLAYBACK_START_TIMEOUT, DEFAULT_PLAYBACK_START_TIMEOUT
            ),
            "failure_notify_ha": current.get(
                CONF_FAILURE_NOTIFY_HA, DEFAULT_FAILURE_NOTIFY_HA
            ),
            "direct_ideal_on_select": current.get(
                CONF_PLAY_IDEAL_ON_SELECT, DEFAULT_PLAY_IDEAL_ON_SELECT
            ),
            "account_enabled": current.get(
                CONF_ACCOUNT_ENABLED, DEFAULT_ACCOUNT_ENABLED
            ),
            "account_provider_mode": current.get(
                CONF_ACCOUNT_PROVIDER_MODE, DEFAULT_ACCOUNT_PROVIDER_MODE
            ),
            "latin_profile_available": self.coordinator.manager.has_profile(
                PROFILE_LATIN
            ),
            "sports_profile_available": self.coordinator.manager.has_profile(
                PROFILE_SPORTS
            ),
        }


class StremioAccountLinkedSensor(CoordinatorEntity, BinarySensorEntity):
    """Expose safe account status and keep account polling active."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Cuenta Stremio"

    def __init__(self, entry: ConfigEntry, runtime: StremioAccountRuntime) -> None:
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_stremio_account"
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
        user = data.get("user", {}) if isinstance(data.get("user"), dict) else {}
        return {
            "email": user.get("email"),
            "provider_mode": self._runtime.provider_mode,
            "library_count": data.get("library_count", 0),
            "continue_watching_count": data.get("continue_watching_count", 0),
            "account_addon_count": data.get("addon_count", 0),
            "account_addons": data.get("addons", []),
            "progress_sync": True,
            "password_stored": False,
        }

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self._runtime.tracker is not None:
            await self._runtime.tracker.async_stop()
        remove_account_runtime(self.hass, self._entry.entry_id)
