"""Config flow for Stremio Stream Bridge."""

from __future__ import annotations

import hashlib
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
    DEFAULT_MAX_SIZE_GB,
    DEFAULT_OPENSUBTITLES_MANIFEST,
    DEFAULT_PLAY_IDEAL_ON_SELECT,
    DEFAULT_PREFERRED_QUALITY,
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


def _as_lines(value: object, fallback: str = "") -> str:
    urls = parse_manifest_urls(value)
    return "\n".join(urls) if urls else fallback


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
                default=defaults.get(CONF_STREAMING_SERVER_URL, "http://192.168.1.50:11470"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Required(
                CONF_CATALOG_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_CATALOG_MANIFEST_URLS), DEFAULT_CINEMETA_MANIFEST
                ),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_STREAM_MANIFEST_URLS,
                default=_as_lines(
                    defaults.get(CONF_STREAM_MANIFEST_URLS), DEFAULT_TORRENTIO_MANIFEST
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
                default=_as_lines(defaults.get(CONF_LATIN_MANIFEST_URLS)),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_SPORTS_MANIFEST_URLS,
                default=_as_lines(defaults.get(CONF_SPORTS_MANIFEST_URLS)),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            player_key: EntitySelector(EntitySelectorConfig(domain="media_player")),
        }
    )


async def _validate(
    hass,
    server_url: str,
    catalog_urls: list[str],
    stream_urls: list[str],
    subtitle_urls: list[str] | None = None,
    latin_urls: list[str] | None = None,
    sports_urls: list[str] | None = None,
) -> tuple[StremioAddonManager, dict[str, Any]]:
    session = async_get_clientsession(hass)
    server = StremioStreamServerClient(session, server_url)
    manager = StremioAddonManager(
        _clients(session, catalog_urls),
        _clients(session, stream_urls),
        _clients(session, subtitle_urls or []),
        _clients(session, latin_urls or []),
        _clients(session, sports_urls or []),
    )
    settings = await server.get_settings()
    await manager.async_refresh()
    if not manager.catalogs():
        raise StremioBridgeError("No configured add-on exposes catalogs")
    if not any(
        "stream" in addon.roles and manifest_has_resource(addon.manifest, "stream")
        for addon in manager.addons
    ):
        raise StremioBridgeError("No default stream provider was loaded")
    if subtitle_urls and not any(
        "subtitle" in addon.roles
        and manifest_has_resource(addon.manifest, "subtitles")
        for addon in manager.addons
    ):
        raise StremioBridgeError("No subtitle provider was loaded")
    if latin_urls and not any(
        PROFILE_LATIN in addon.roles and manifest_has_resource(addon.manifest, "stream")
        for addon in manager.addons
    ):
        raise StremioBridgeError("The Latin provider does not expose streams")
    if sports_urls:
        if not any(
            PROFILE_SPORTS in addon.roles and manifest_has_resource(addon.manifest, "stream")
            for addon in manager.addons
        ):
            raise StremioBridgeError("The sports provider does not expose streams")
        if not manager.catalogs(profile=PROFILE_SPORTS):
            raise StremioBridgeError("The sports provider does not expose a browsable catalog")
    return manager, settings


class StremioStreamBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration from the Home Assistant UI."""

    VERSION = 4

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_url = normalize_url(user_input[CONF_STREAMING_SERVER_URL])
                catalog_urls = parse_manifest_urls(user_input[CONF_CATALOG_MANIFEST_URLS])
                stream_urls = parse_manifest_urls(user_input[CONF_STREAM_MANIFEST_URLS])
                subtitle_urls = parse_manifest_urls(
                    user_input.get(CONF_SUBTITLE_MANIFEST_URLS, "")
                )
                latin_urls = parse_manifest_urls(user_input.get(CONF_LATIN_MANIFEST_URLS, ""))
                sports_urls = parse_manifest_urls(
                    user_input.get(CONF_SPORTS_MANIFEST_URLS, "")
                )
                if not catalog_urls or not stream_urls:
                    raise StremioBridgeError(
                        "At least one catalog and stream manifest is required"
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
            except StremioBridgeError:
                errors["base"] = "cannot_connect"
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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                catalog_urls = parse_manifest_urls(user_input[CONF_CATALOG_MANIFEST_URLS])
                stream_urls = parse_manifest_urls(user_input[CONF_STREAM_MANIFEST_URLS])
                subtitle_urls = parse_manifest_urls(
                    user_input.get(CONF_SUBTITLE_MANIFEST_URLS, "")
                )
                latin_urls = parse_manifest_urls(user_input.get(CONF_LATIN_MANIFEST_URLS, ""))
                sports_urls = parse_manifest_urls(
                    user_input.get(CONF_SPORTS_MANIFEST_URLS, "")
                )
                if not catalog_urls or not stream_urls:
                    raise StremioBridgeError("Manifest lists cannot be empty")
                await _validate(
                    self.hass,
                    self.config_entry.data[CONF_STREAMING_SERVER_URL],
                    catalog_urls,
                    stream_urls,
                    subtitle_urls,
                    latin_urls,
                    sports_urls,
                )
            except StremioBridgeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    data={
                        **user_input,
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
                    CONF_CATALOG_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_CATALOG_MANIFEST_URLS), DEFAULT_CINEMETA_MANIFEST
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_STREAM_MANIFEST_URLS,
                    default=_as_lines(
                        current.get(CONF_STREAM_MANIFEST_URLS), DEFAULT_TORRENTIO_MANIFEST
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_LATIN_MANIFEST_URLS,
                    default=_as_lines(current.get(CONF_LATIN_MANIFEST_URLS)),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_SPORTS_MANIFEST_URLS,
                    default=_as_lines(current.get(CONF_SPORTS_MANIFEST_URLS)),
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
                    default=current.get(
                        CONF_PLAY_IDEAL_ON_SELECT, DEFAULT_PLAY_IDEAL_ON_SELECT
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_IDEAL_LINK_FILTER,
                    default=current.get(
                        CONF_IDEAL_LINK_FILTER, DEFAULT_IDEAL_LINK_FILTER
                    ),
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
                    default=current.get(
                        CONF_SUBTITLE_LANGUAGES, DEFAULT_SUBTITLE_LANGUAGES
                    ),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Required(
                    CONF_SUBTITLE_CONVERT_VTT,
                    default=current.get(
                        CONF_SUBTITLE_CONVERT_VTT, DEFAULT_SUBTITLE_CONVERT_VTT
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_SUBTITLE_BASE_URL,
                    default=current.get(CONF_SUBTITLE_BASE_URL, DEFAULT_SUBTITLE_BASE_URL),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
