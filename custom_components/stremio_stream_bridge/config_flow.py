"""Config flow for Stremio Stream Bridge."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .aggregator import StremioAddonManager, manifest_has_resource
from .api import (
    StremioAddonClient,
    StremioBridgeError,
    StremioStreamServerClient,
    normalize_url,
    parse_manifest_urls,
)
from .const import (
    AUDIO_MODE_OPTIONS,
    CONF_AUDIO_MODE,
    CONF_CATALOG_MANIFEST_URLS,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_EXCLUDE_KEYWORDS,
    CONF_IDEAL_LINK_FILTER,
    CONF_LATIN_MANIFEST_URLS,
    CONF_MAX_SIZE_GB,
    CONF_PLAY_IDEAL_ON_SELECT,
    CONF_PREFERRED_QUALITY,
    CONF_SPORTS_MANIFEST_URLS,
    CONF_STREAM_MANIFEST_URLS,
    CONF_STREAMING_SERVER_URL,
    CONF_SUBTITLE_BASE_URL,
    CONF_SUBTITLE_CONVERT_VTT,
    CONF_SUBTITLE_LANGUAGES,
    CONF_SUBTITLE_MANIFEST_URLS,
    CONF_SUBTITLE_MODE,
    DEFAULT_AUDIO_MODE,
    DEFAULT_CINEMETA_MANIFEST,
    DEFAULT_EXCLUDE_KEYWORDS,
    DEFAULT_IDEAL_LINK_FILTER,
    DEFAULT_LATIN_MANIFEST,
    DEFAULT_MAX_SIZE_GB,
    DEFAULT_OPENSUBTITLES_MANIFEST,
    DEFAULT_PLAY_IDEAL_ON_SELECT,
    DEFAULT_PREFERRED_QUALITY,
    DEFAULT_SPORTS_MANIFEST,
    DEFAULT_STREAMING_SERVER_URL,
    DEFAULT_SUBTITLE_BASE_URL,
    DEFAULT_SUBTITLE_CONVERT_VTT,
    DEFAULT_SUBTITLE_LANGUAGES,
    DEFAULT_SUBTITLE_MODE,
    DEFAULT_TORRENTIO_MANIFEST,
    DOMAIN,
    PROFILE_LATIN,
    PROFILE_SPORTS,
    QUALITY_OPTIONS,
    SUBTITLE_MODE_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


class FlowValidationError(StremioBridgeError):
    """Validation error associated with a specific form field."""

    def __init__(self, field: str, code: str, detail: str) -> None:
        super().__init__(detail)
        self.field = field
        self.code = code
        self.detail = detail


def _as_lines(value: object | None, fallback: str = "") -> str:
    """Convert stored manifest lists to UI text while preserving explicit blanks."""
    if value is None:
        return fallback
    return "\n".join(parse_manifest_urls(value))


def _clients(session, urls: list[str]) -> list[StremioAddonClient]:
    return [StremioAddonClient(session, url) for url in urls]


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    player_key = (
        vol.Required(
            CONF_DEFAULT_MEDIA_PLAYER,
            default=defaults[CONF_DEFAULT_MEDIA_PLAYER],
        )
        if defaults.get(CONF_DEFAULT_MEDIA_PLAYER)
        else vol.Required(CONF_DEFAULT_MEDIA_PLAYER)
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_STREAMING_SERVER_URL,
                default=defaults.get(CONF_STREAMING_SERVER_URL, DEFAULT_STREAMING_SERVER_URL),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Required(
                CONF_CATALOG_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_CATALOG_MANIFEST_URLS),
                    DEFAULT_CINEMETA_MANIFEST,
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_STREAM_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_STREAM_MANIFEST_URLS),
                    DEFAULT_TORRENTIO_MANIFEST,
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_SUBTITLE_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_SUBTITLE_MANIFEST_URLS),
                    DEFAULT_OPENSUBTITLES_MANIFEST,
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_LATIN_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_LATIN_MANIFEST_URLS),
                    DEFAULT_LATIN_MANIFEST,
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_SPORTS_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_SPORTS_MANIFEST_URLS),
                    DEFAULT_SPORTS_MANIFEST,
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            player_key: EntitySelector(EntitySelectorConfig(domain="media_player")),
        }
    )


def _errors_for_urls(manager: StremioAddonManager, urls: list[str]) -> str:
    messages = [f"{url}: {manager.errors[url]}" for url in urls if url in manager.errors]
    return "; ".join(messages)


async def _validate(
    hass,
    server_url: str,
    catalog_urls: list[str],
    stream_urls: list[str],
    subtitle_urls: list[str] | None = None,
    latin_urls: list[str] | None = None,
    sports_urls: list[str] | None = None,
) -> tuple[StremioAddonManager, dict[str, Any]]:
    """Validate required providers and collect non-blocking connectivity warnings."""
    session = async_get_clientsession(hass)
    server = StremioStreamServerClient(session, server_url)
    manager = StremioAddonManager(
        _clients(session, catalog_urls),
        _clients(session, stream_urls),
        _clients(session, subtitle_urls or []),
        _clients(session, latin_urls or []),
        _clients(session, sports_urls or []),
    )

    server_error: str | None = None
    settings: dict[str, Any] = {}
    try:
        settings = await server.get_settings()
    except StremioBridgeError as err:
        # Let the entry be created so the connectivity sensor and diagnostics action
        # can explain LAN binding/firewall problems. Direct HTTP sports streams can
        # still work while the torrent server is offline.
        server_error = str(err)
        _LOGGER.warning("Stream-server validation warning: %s", err)

    try:
        await manager.async_refresh()
    except StremioBridgeError as err:
        raise FlowValidationError(
            CONF_CATALOG_MANIFEST_URLS,
            "no_addons_loaded",
            str(err),
        ) from err

    if not manager.catalogs():
        detail = _errors_for_urls(manager, catalog_urls) or (
            "No configured catalog add-on declares a browsable catalog"
        )
        raise FlowValidationError(
            CONF_CATALOG_MANIFEST_URLS,
            "catalog_provider_unavailable",
            detail,
        )

    if not any(
        "stream" in addon.roles and manifest_has_resource(addon.manifest, "stream")
        for addon in manager.addons
    ):
        detail = _errors_for_urls(manager, stream_urls) or (
            "No configured default provider declares the stream resource"
        )
        raise FlowValidationError(
            CONF_STREAM_MANIFEST_URLS,
            "stream_provider_unavailable",
            detail,
        )

    warnings: dict[str, str] = {}
    optional_groups = {
        CONF_SUBTITLE_MANIFEST_URLS: subtitle_urls or [],
        CONF_LATIN_MANIFEST_URLS: latin_urls or [],
        CONF_SPORTS_MANIFEST_URLS: sports_urls or [],
    }
    for field, urls in optional_groups.items():
        if detail := _errors_for_urls(manager, urls):
            warnings[field] = detail

    if latin_urls and not any(
        PROFILE_LATIN in addon.roles and manifest_has_resource(addon.manifest, "stream")
        for addon in manager.addons
    ):
        warnings.setdefault(
            CONF_LATIN_MANIFEST_URLS,
            "No currently loaded Latin add-on declares the stream resource",
        )

    if sports_urls:
        if not any(
            PROFILE_SPORTS in addon.roles and manifest_has_resource(addon.manifest, "stream")
            for addon in manager.addons
        ):
            warnings.setdefault(
                CONF_SPORTS_MANIFEST_URLS,
                "No currently loaded sports add-on declares the stream resource",
            )
        elif not manager.catalogs(profile=PROFILE_SPORTS):
            warnings.setdefault(
                CONF_SPORTS_MANIFEST_URLS,
                "The sports add-on loaded but did not expose a browsable catalog",
            )

    for field, detail in warnings.items():
        _LOGGER.warning("Optional provider warning for %s: %s", field, detail)

    return manager, {
        "settings": settings,
        "server_online": server_error is None,
        "server_error": server_error,
        "warnings": warnings,
    }


class StremioStreamBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration from the Home Assistant UI."""

    VERSION = 5

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_url = normalize_url(user_input[CONF_STREAMING_SERVER_URL])
                catalog_urls = parse_manifest_urls(user_input[CONF_CATALOG_MANIFEST_URLS])
                stream_urls = parse_manifest_urls(user_input[CONF_STREAM_MANIFEST_URLS])
                subtitle_urls = parse_manifest_urls(user_input.get(CONF_SUBTITLE_MANIFEST_URLS, ""))
                latin_urls = parse_manifest_urls(user_input.get(CONF_LATIN_MANIFEST_URLS, ""))
                sports_urls = parse_manifest_urls(user_input.get(CONF_SPORTS_MANIFEST_URLS, ""))
                if not catalog_urls:
                    raise FlowValidationError(
                        CONF_CATALOG_MANIFEST_URLS,
                        "catalog_provider_unavailable",
                        "At least one catalog manifest is required",
                    )
                if not stream_urls:
                    raise FlowValidationError(
                        CONF_STREAM_MANIFEST_URLS,
                        "stream_provider_unavailable",
                        "At least one stream manifest is required",
                    )
                await _validate(
                    self.hass,
                    server_url,
                    catalog_urls,
                    stream_urls,
                    subtitle_urls,
                    latin_urls,
                    sports_urls,
                )
            except FlowValidationError as err:
                errors[err.field] = err.code
                _LOGGER.warning("Configuration validation failed: %s", err.detail)
            except StremioBridgeError as err:
                errors["base"] = "cannot_connect"
                _LOGGER.warning("Configuration validation failed: %s", err)
            else:
                unique_id = hashlib.sha256(server_url.encode()).hexdigest()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_STREAMING_SERVER_URL: server_url,
                    CONF_CATALOG_MANIFEST_URLS: catalog_urls,
                    CONF_STREAM_MANIFEST_URLS: stream_urls,
                    CONF_SUBTITLE_MANIFEST_URLS: subtitle_urls,
                    CONF_LATIN_MANIFEST_URLS: latin_urls,
                    CONF_SPORTS_MANIFEST_URLS: sports_urls,
                    CONF_DEFAULT_MEDIA_PLAYER: user_input[CONF_DEFAULT_MEDIA_PLAYER],
                }
                return self.async_create_entry(title="Stremio Media", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return StremioStreamBridgeOptionsFlow()


class StremioStreamBridgeOptionsFlow(config_entries.OptionsFlowWithReload):
    """Change providers and playback preferences, then reload automatically."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_url = normalize_url(user_input[CONF_STREAMING_SERVER_URL])
                catalog_urls = parse_manifest_urls(user_input[CONF_CATALOG_MANIFEST_URLS])
                stream_urls = parse_manifest_urls(user_input[CONF_STREAM_MANIFEST_URLS])
                subtitle_urls = parse_manifest_urls(user_input.get(CONF_SUBTITLE_MANIFEST_URLS, ""))
                latin_urls = parse_manifest_urls(user_input.get(CONF_LATIN_MANIFEST_URLS, ""))
                sports_urls = parse_manifest_urls(user_input.get(CONF_SPORTS_MANIFEST_URLS, ""))
                if not catalog_urls:
                    raise FlowValidationError(
                        CONF_CATALOG_MANIFEST_URLS,
                        "catalog_provider_unavailable",
                        "At least one catalog manifest is required",
                    )
                if not stream_urls:
                    raise FlowValidationError(
                        CONF_STREAM_MANIFEST_URLS,
                        "stream_provider_unavailable",
                        "At least one stream manifest is required",
                    )
                await _validate(
                    self.hass,
                    server_url,
                    catalog_urls,
                    stream_urls,
                    subtitle_urls,
                    latin_urls,
                    sports_urls,
                )
            except FlowValidationError as err:
                errors[err.field] = err.code
                _LOGGER.warning("Options validation failed: %s", err.detail)
            except StremioBridgeError as err:
                errors["base"] = "cannot_connect"
                _LOGGER.warning("Options validation failed: %s", err)
            else:
                return self.async_create_entry(
                    data={
                        **user_input,
                        CONF_STREAMING_SERVER_URL: server_url,
                        CONF_CATALOG_MANIFEST_URLS: catalog_urls,
                        CONF_STREAM_MANIFEST_URLS: stream_urls,
                        CONF_SUBTITLE_MANIFEST_URLS: subtitle_urls,
                        CONF_LATIN_MANIFEST_URLS: latin_urls,
                        CONF_SPORTS_MANIFEST_URLS: sports_urls,
                    }
                )

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_MEDIA_PLAYER,
                    default=current.get(CONF_DEFAULT_MEDIA_PLAYER),
                ): EntitySelector(EntitySelectorConfig(domain="media_player")),
                vol.Required(
                    CONF_STREAMING_SERVER_URL,
                    default=current.get(CONF_STREAMING_SERVER_URL, DEFAULT_STREAMING_SERVER_URL),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(
                    CONF_CATALOG_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_CATALOG_MANIFEST_URLS),
                        DEFAULT_CINEMETA_MANIFEST,
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_STREAM_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_STREAM_MANIFEST_URLS),
                        DEFAULT_TORRENTIO_MANIFEST,
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_LATIN_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_LATIN_MANIFEST_URLS),
                        DEFAULT_LATIN_MANIFEST,
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_SPORTS_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_SPORTS_MANIFEST_URLS),
                        DEFAULT_SPORTS_MANIFEST,
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_SUBTITLE_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_SUBTITLE_MANIFEST_URLS),
                        DEFAULT_OPENSUBTITLES_MANIFEST,
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_PLAY_IDEAL_ON_SELECT,
                    default=current.get(CONF_PLAY_IDEAL_ON_SELECT, DEFAULT_PLAY_IDEAL_ON_SELECT),
                ): BooleanSelector(),
                vol.Required(
                    CONF_IDEAL_LINK_FILTER,
                    default=current.get(CONF_IDEAL_LINK_FILTER, DEFAULT_IDEAL_LINK_FILTER),
                ): BooleanSelector(),
                vol.Required(
                    CONF_AUDIO_MODE,
                    default=current.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE),
                ): SelectSelector(SelectSelectorConfig(options=AUDIO_MODE_OPTIONS)),
                vol.Required(
                    CONF_PREFERRED_QUALITY,
                    default=current.get(CONF_PREFERRED_QUALITY, DEFAULT_PREFERRED_QUALITY),
                ): SelectSelector(SelectSelectorConfig(options=QUALITY_OPTIONS)),
                vol.Required(
                    CONF_MAX_SIZE_GB,
                    default=current.get(CONF_MAX_SIZE_GB, DEFAULT_MAX_SIZE_GB),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=200,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_EXCLUDE_KEYWORDS,
                    default=current.get(CONF_EXCLUDE_KEYWORDS, DEFAULT_EXCLUDE_KEYWORDS),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Required(
                    CONF_SUBTITLE_MODE,
                    default=current.get(CONF_SUBTITLE_MODE, DEFAULT_SUBTITLE_MODE),
                ): SelectSelector(SelectSelectorConfig(options=SUBTITLE_MODE_OPTIONS)),
                vol.Required(
                    CONF_SUBTITLE_LANGUAGES,
                    default=current.get(CONF_SUBTITLE_LANGUAGES, DEFAULT_SUBTITLE_LANGUAGES),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Required(
                    CONF_SUBTITLE_CONVERT_VTT,
                    default=current.get(CONF_SUBTITLE_CONVERT_VTT, DEFAULT_SUBTITLE_CONVERT_VTT),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_SUBTITLE_BASE_URL,
                    default=current.get(CONF_SUBTITLE_BASE_URL, DEFAULT_SUBTITLE_BASE_URL),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
