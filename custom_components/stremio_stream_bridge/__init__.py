"""Stremio Stream Bridge integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .aggregator import StremioAddonManager, stream_key
from .api import (
    StremioAddonClient,
    StremioBridgeError,
    StremioStreamServerClient,
    guess_mime_type,
    parse_manifest_urls,
)
from .cast_style import install_no_edge_subtitle_patch
from .const import (
    ATTR_DISABLE_SUBTITLES,
    ATTR_ENTRY_ID,
    ATTR_MEDIA_ID,
    ATTR_MEDIA_PLAYER,
    ATTR_MEDIA_TYPE,
    ATTR_PROFILE,
    ATTR_QUERY,
    ATTR_STREAM_INDEX,
    ATTR_URL,
    CONF_ADDON_MANIFEST_URL,
    CONF_CATALOG_MANIFEST_URLS,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_DEFAULT_STREAM_INDEX,
    CONF_EXCLUDE_KEYWORDS,
    CONF_IDEAL_LINK_FILTER,
    CONF_LATIN_MANIFEST_URLS,
    CONF_MAX_SIZE_GB,
    CONF_PREFERRED_QUALITY,
    CONF_SPORTS_MANIFEST_URLS,
    CONF_STREAM_MANIFEST_URLS,
    CONF_STREAMING_SERVER_URL,
    CONF_SUBTITLE_BASE_URL,
    CONF_SUBTITLE_CONVERT_VTT,
    CONF_SUBTITLE_LANGUAGES,
    CONF_SUBTITLE_MANIFEST_URLS,
    DEFAULT_CINEMETA_MANIFEST,
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_IDEAL_LINK_FILTER,
    DEFAULT_LATIN_MANIFEST,
    DEFAULT_MAX_SIZE_GB,
    DEFAULT_OPENSUBTITLES_MANIFEST,
    DEFAULT_PREFERRED_QUALITY,
    DEFAULT_SPORTS_MANIFEST,
    DEFAULT_STREAMING_SERVER_URL,
    DEFAULT_SUBTITLE_CONVERT_VTT,
    DEFAULT_SUBTITLE_LANGUAGES,
    DEFAULT_TORRENTIO_MANIFEST,
    DOMAIN,
    PLATFORMS,
    PROFILE_DEFAULT,
    PROFILE_LATIN,
    PROFILE_OPTIONS,
    PROFILE_SPORTS,
    SERVICE_CONNECTION_DIAGNOSTICS,
    SERVICE_PLAY,
    SERVICE_PLAY_URL,
    SERVICE_REFRESH,
    SERVICE_SEARCH,
    SERVICE_SUBTITLE_DIAGNOSTICS,
)
from .coordinator import StremioBridgeCoordinator
from .playback import prepare_playback
from .stream_selector import choose_best_stream, choose_ideal_stream
from .subtitle_proxy import SubtitleProxy, SubtitleProxyError, SubtitleProxyView
from .subtitle_support import (
    async_prepare_subtitle_track,
    cast_service_extra,
    choose_subtitle,
    is_cast_player,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class StremioBridgeRuntime:
    """Runtime data attached to a config entry."""

    manager: StremioAddonManager
    server: StremioStreamServerClient
    coordinator: StremioBridgeCoordinator
    subtitle_proxy: SubtitleProxy
    last_search_query: str | None = None
    last_search_results: list[dict[str, Any]] = field(default_factory=list)


PLAY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_TYPE): cv.string,
        vol.Required(ATTR_MEDIA_ID): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(ATTR_STREAM_INDEX): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_DISABLE_SUBTITLES, default=False): cv.boolean,
        vol.Optional(ATTR_PROFILE, default=PROFILE_DEFAULT): vol.In(PROFILE_OPTIONS),
    }
)

PLAY_URL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_URL): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
    }
)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_MEDIA_TYPE, default="all"): vol.In(["all", "movie", "series"]),
    }
)

CONNECTION_DIAGNOSTICS_SCHEMA = REFRESH_SCHEMA

SUBTITLE_DIAGNOSTICS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEDIA_TYPE): cv.string,
        vol.Required(ATTR_MEDIA_ID): cv.string,
        vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(ATTR_STREAM_INDEX): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register services, subtitle endpoint and Cast subtitle styling."""
    install_no_edge_subtitle_patch()
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "subtitle_proxy" not in domain_data:
        subtitle_proxy = SubtitleProxy(hass, async_get_clientsession(hass))
        domain_data["subtitle_proxy"] = subtitle_proxy
        hass.http.register_view(SubtitleProxyView(subtitle_proxy))

    async def handle_play(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        runtime: StremioBridgeRuntime = entry.runtime_data
        media_type = call.data[ATTR_MEDIA_TYPE]
        media_id = call.data[ATTR_MEDIA_ID]
        profile = str(call.data.get(ATTR_PROFILE, PROFILE_DEFAULT))
        streams = await runtime.manager.get_streams(media_type, media_id, profile)
        if not streams:
            raise HomeAssistantError("No stream provider returned a playable source")
        current = {**entry.data, **entry.options}
        try:
            stream = _select_stream(
                entry,
                streams,
                call.data.get(ATTR_STREAM_INDEX),
                profile=profile,
            )
            url, mime_type = prepare_playback(
                runtime.server,
                stream,
                current,
                profile=profile,
            )
        except (StremioBridgeError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
        player = _resolve_player(entry, call.data.get(ATTR_MEDIA_PLAYER))
        subtitle = None
        cast_target = is_cast_player(hass, player)
        subtitles_disabled = bool(call.data.get(ATTR_DISABLE_SUBTITLES)) or profile in {
            PROFILE_LATIN,
            PROFILE_SPORTS,
        }
        if cast_target and not subtitles_disabled:
            subtitle = await async_prepare_subtitle_track(
                runtime.manager,
                runtime.server,
                runtime.subtitle_proxy,
                current,
                media_type,
                media_id,
                stream,
            )
        elif not subtitles_disabled and not cast_target:
            _LOGGER.warning(
                "External subtitles were skipped because %s is not a Home Assistant Cast entity",
                player,
            )
        title = media_id
        thumbnail = None
        try:
            meta = await runtime.manager.get_meta(
                media_type,
                media_id.split(":", 1)[0],
                profile,
            )
            title = str(meta.get("name") or meta.get("title") or media_id)
            thumbnail = meta.get("poster") or meta.get("background")
        except StremioBridgeError:
            pass
        extra = (
            cast_service_extra(subtitle, title=title, thumbnail=thumbnail) if cast_target else None
        )
        await _async_play_url(
            hass,
            call,
            player,
            url,
            mime_type=mime_type,
            extra=extra,
        )

    async def handle_play_url(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        runtime: StremioBridgeRuntime = entry.runtime_data
        raw_url = call.data[ATTR_URL].strip()
        try:
            url = (
                runtime.server.resolve_magnet(raw_url) if raw_url.startswith("magnet:") else raw_url
            )
        except StremioBridgeError as err:
            raise HomeAssistantError(str(err)) from err
        if not url.startswith(("http://", "https://")):
            raise HomeAssistantError("play_url accepts HTTP(S) URLs or magnet URIs")
        player = _resolve_player(entry, call.data.get(ATTR_MEDIA_PLAYER))
        await _async_play_url(hass, call, player, url)

    async def handle_refresh(call: ServiceCall) -> None:
        if entry_id := call.data.get(ATTR_ENTRY_ID):
            await _resolve_entry(hass, entry_id).runtime_data.coordinator.async_request_refresh()
            return
        for entry in _loaded_entries(hass):
            await entry.runtime_data.coordinator.async_request_refresh()

    async def handle_search(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        runtime: StremioBridgeRuntime = entry.runtime_data
        media_type = call.data[ATTR_MEDIA_TYPE]
        media_types = ("movie", "series") if media_type == "all" else (media_type,)
        runtime.last_search_query = call.data[ATTR_QUERY].strip()
        runtime.last_search_results = await runtime.manager.search(
            runtime.last_search_query, media_types
        )

    async def handle_connection_diagnostics(call: ServiceCall) -> dict[str, Any]:
        """Test every endpoint independently and return exact failures."""
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        runtime: StremioBridgeRuntime = entry.runtime_data
        current = {**entry.data, **entry.options}
        response: dict[str, Any] = {
            "ok": True,
            "stream_server": {
                "url": current.get(CONF_STREAMING_SERVER_URL, DEFAULT_STREAMING_SERVER_URL)
            },
            "providers": {},
        }
        try:
            settings = await runtime.server.get_settings()
        except StremioBridgeError as err:
            response["ok"] = False
            response["stream_server"].update(
                {"ok": False, "error": str(err), "test_path": "/settings"}
            )
        else:
            values = settings.get("values", settings) if isinstance(settings, dict) else {}
            response["stream_server"].update(
                {
                    "ok": True,
                    "server_version": values.get("serverVersion")
                    if isinstance(values, dict)
                    else None,
                }
            )

        session = async_get_clientsession(hass)
        groups = {
            "catalog": parse_manifest_urls(
                current.get(CONF_CATALOG_MANIFEST_URLS, [DEFAULT_CINEMETA_MANIFEST])
            ),
            "stream": parse_manifest_urls(
                current.get(CONF_STREAM_MANIFEST_URLS, [DEFAULT_TORRENTIO_MANIFEST])
            ),
            "subtitles": parse_manifest_urls(
                current.get(CONF_SUBTITLE_MANIFEST_URLS, [DEFAULT_OPENSUBTITLES_MANIFEST])
            ),
            "latin": parse_manifest_urls(
                current.get(CONF_LATIN_MANIFEST_URLS, [DEFAULT_LATIN_MANIFEST])
            ),
            "sports": parse_manifest_urls(
                current.get(CONF_SPORTS_MANIFEST_URLS, [DEFAULT_SPORTS_MANIFEST])
            ),
        }
        for group, urls in groups.items():
            checks: list[dict[str, Any]] = []
            for manifest_url in urls:
                client = StremioAddonClient(session, manifest_url)
                item: dict[str, Any] = {"url": client.manifest_url}
                try:
                    manifest = await client.get_manifest()
                except StremioBridgeError as err:
                    item.update({"ok": False, "error": str(err)})
                    response["ok"] = False
                else:
                    resources = manifest.get("resources", [])
                    resource_names = [
                        resource if isinstance(resource, str) else resource.get("name")
                        for resource in resources
                        if isinstance(resource, (str, dict))
                    ]
                    catalogs = manifest.get("catalogs", [])
                    item.update(
                        {
                            "ok": True,
                            "id": manifest.get("id"),
                            "name": manifest.get("name"),
                            "version": manifest.get("version"),
                            "types": manifest.get("types", []),
                            "resources": resource_names,
                            "catalog_count": len(catalogs) if isinstance(catalogs, list) else 0,
                        }
                    )
                checks.append(item)
            response["providers"][group] = checks
        return response

    async def handle_subtitle_diagnostics(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        runtime: StremioBridgeRuntime = entry.runtime_data
        media_type = call.data[ATTR_MEDIA_TYPE]
        media_id = call.data[ATTR_MEDIA_ID]
        streams = await runtime.manager.get_streams(media_type, media_id, PROFILE_DEFAULT)
        if not streams:
            return {"ok": False, "error": "No stream provider returned a source"}
        stream = _select_stream(
            entry,
            streams,
            call.data.get(ATTR_STREAM_INDEX),
            profile=PROFILE_DEFAULT,
        )
        current = {**entry.data, **entry.options}
        subtitles = await runtime.manager.get_subtitles(media_type, media_id, None, stream)
        selected = choose_subtitle(
            subtitles,
            current.get(CONF_SUBTITLE_LANGUAGES, DEFAULT_SUBTITLE_LANGUAGES),
        )
        player = _resolve_player(entry, call.data.get(ATTR_MEDIA_PLAYER))
        response: dict[str, Any] = {
            "ok": selected is not None,
            "media_type": media_type,
            "media_id": media_id,
            "player": player,
            "cast_entity": is_cast_player(hass, player),
            "subtitle_border": "none",
            "subtitle_count": len(subtitles),
            "available_languages": sorted({str(item.get("lang") or "und") for item in subtitles}),
            "preferred_languages": current.get(CONF_SUBTITLE_LANGUAGES, DEFAULT_SUBTITLE_LANGUAGES),
            "provider_errors": dict(runtime.manager.last_subtitle_errors),
        }
        if selected is None:
            response["error"] = "No subtitle matched the preferred languages"
            return response
        raw_url = str(selected["url"])
        response.update(
            {
                "selected_language": selected.get("lang"),
                "selected_provider": selected.get("_bridge_addon_name"),
                "source_url": raw_url,
            }
        )
        if bool(current.get(CONF_SUBTITLE_CONVERT_VTT, DEFAULT_SUBTITLE_CONVERT_VTT)):
            try:
                response["delivery_url"] = await runtime.subtitle_proxy.async_prepare_url(
                    raw_url,
                    str(current.get(CONF_SUBTITLE_BASE_URL, "") or ""),
                )
                response["delivery_method"] = "home_assistant_webvtt_proxy"
            except SubtitleProxyError as err:
                response["ok"] = False
                response["error"] = str(err)
        else:
            response["delivery_url"] = raw_url
            response["delivery_method"] = "provider_url"
        return response

    hass.services.async_register(DOMAIN, SERVICE_PLAY, handle_play, schema=PLAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PLAY_URL, handle_play_url, schema=PLAY_URL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEARCH, handle_search, schema=SEARCH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_CONNECTION_DIAGNOSTICS,
        handle_connection_diagnostics,
        schema=CONNECTION_DIAGNOSTICS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBTITLE_DIAGNOSTICS,
        handle_subtitle_diagnostics,
        schema=SUBTITLE_DIAGNOSTICS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older entries to the resilient v0.4.1 format."""
    data = dict(entry.data)
    version = entry.version
    if version < 2:
        legacy_url = data.get(CONF_ADDON_MANIFEST_URL)
        catalog_urls = [DEFAULT_CINEMETA_MANIFEST]
        stream_urls = [DEFAULT_TORRENTIO_MANIFEST]
        if isinstance(legacy_url, str) and legacy_url:
            catalog_urls.insert(0, legacy_url)
            stream_urls = [legacy_url]
        data[CONF_CATALOG_MANIFEST_URLS] = parse_manifest_urls(catalog_urls)
        data[CONF_STREAM_MANIFEST_URLS] = parse_manifest_urls(stream_urls)
        version = 2
    if version < 3:
        data.setdefault(
            CONF_SUBTITLE_MANIFEST_URLS,
            parse_manifest_urls([DEFAULT_OPENSUBTITLES_MANIFEST]),
        )
        version = 3
    if version < 4:
        data.setdefault(CONF_LATIN_MANIFEST_URLS, [])
        data.setdefault(CONF_SPORTS_MANIFEST_URLS, [])
        version = 4
    if version < 5:
        if data.get(CONF_STREAMING_SERVER_URL) == "http://192.168.1.50:11470":
            data[CONF_STREAMING_SERVER_URL] = DEFAULT_STREAMING_SERVER_URL
        if not parse_manifest_urls(data.get(CONF_LATIN_MANIFEST_URLS, [])):
            data[CONF_LATIN_MANIFEST_URLS] = [DEFAULT_LATIN_MANIFEST]
        if not parse_manifest_urls(data.get(CONF_SPORTS_MANIFEST_URLS, [])):
            data[CONF_SPORTS_MANIFEST_URLS] = [DEFAULT_SPORTS_MANIFEST]
        version = 5
    hass.config_entries.async_update_entry(entry, data=data, version=version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one aggregate Stremio environment."""
    session = async_get_clientsession(hass)
    current = {**entry.data, **entry.options}
    catalog_urls = parse_manifest_urls(
        current.get(CONF_CATALOG_MANIFEST_URLS, [DEFAULT_CINEMETA_MANIFEST])
    )
    stream_urls = parse_manifest_urls(
        current.get(CONF_STREAM_MANIFEST_URLS, [DEFAULT_TORRENTIO_MANIFEST])
    )
    subtitle_urls = parse_manifest_urls(
        current.get(CONF_SUBTITLE_MANIFEST_URLS, [DEFAULT_OPENSUBTITLES_MANIFEST])
    )
    latin_urls = parse_manifest_urls(current.get(CONF_LATIN_MANIFEST_URLS, []))
    sports_urls = parse_manifest_urls(current.get(CONF_SPORTS_MANIFEST_URLS, []))
    manager = StremioAddonManager(
        [StremioAddonClient(session, url) for url in catalog_urls],
        [StremioAddonClient(session, url) for url in stream_urls],
        [StremioAddonClient(session, url) for url in subtitle_urls],
        [StremioAddonClient(session, url) for url in latin_urls],
        [StremioAddonClient(session, url) for url in sports_urls],
    )
    server = StremioStreamServerClient(
        session, current.get(CONF_STREAMING_SERVER_URL, DEFAULT_STREAMING_SERVER_URL)
    )
    coordinator = StremioBridgeCoordinator(hass, manager, server)
    await coordinator.async_config_entry_first_refresh()
    subtitle_proxy: SubtitleProxy = hass.data[DOMAIN]["subtitle_proxy"]
    entry.runtime_data = StremioBridgeRuntime(manager, server, coordinator, subtitle_proxy)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok


def _select_stream(
    entry: ConfigEntry,
    streams: list[dict[str, Any]],
    requested_index: int | None,
    *,
    profile: str,
) -> dict[str, Any]:
    if requested_index is not None:
        if requested_index >= len(streams):
            raise HomeAssistantError(
                f"Stream index {requested_index} is unavailable; providers returned "
                f"{len(streams)} stream(s)"
            )
        return streams[requested_index]
    if CONF_DEFAULT_STREAM_INDEX in entry.options:
        legacy_index = int(entry.options[CONF_DEFAULT_STREAM_INDEX])
        if legacy_index < len(streams):
            return streams[legacy_index]
    if profile == PROFILE_SPORTS:
        return streams[0]
    current = {**entry.data, **entry.options}
    max_size = float(current.get(CONF_MAX_SIZE_GB, DEFAULT_MAX_SIZE_GB))
    excluded = str(current.get(CONF_EXCLUDE_KEYWORDS, DEFAULT_EXCLUDE_KEYWORDS))
    if bool(current.get(CONF_IDEAL_LINK_FILTER, DEFAULT_IDEAL_LINK_FILTER)):
        return choose_ideal_stream(streams, max_size, excluded)
    return choose_best_stream(
        streams,
        str(current.get(CONF_PREFERRED_QUALITY, DEFAULT_PREFERRED_QUALITY)),
        max_size,
        excluded,
    )


def find_stream_by_key(streams: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Find a selected stream after re-querying providers."""
    return next((stream for stream in streams if stream_key(stream) == key), None)


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and getattr(entry, "runtime_data", None) is not None
    ]


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    entries = _loaded_entries(hass)
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry not in entries:
            raise HomeAssistantError(f"Stremio Stream Bridge entry {entry_id} is not loaded")
        return entry
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise HomeAssistantError("No loaded Stremio Stream Bridge entries")
    raise HomeAssistantError("More than one entry exists; specify entry_id")


def _resolve_player(entry: ConfigEntry, requested: str | None) -> str:
    player = requested or entry.options.get(
        CONF_DEFAULT_MEDIA_PLAYER,
        entry.data.get(CONF_DEFAULT_MEDIA_PLAYER),
    )
    if not player:
        raise HomeAssistantError("No target media_player was provided or configured")
    return player


async def _async_play_url(
    hass: HomeAssistant,
    call: ServiceCall,
    player: str,
    url: str,
    *,
    mime_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    data: dict[str, Any] = {
        ATTR_ENTITY_ID: player,
        "media_content_id": url,
        "media_content_type": mime_type or guess_mime_type(url),
    }
    if extra:
        data["extra"] = extra
    await hass.services.async_call(
        "media_player",
        "play_media",
        data,
        blocking=True,
        context=call.context,
    )
