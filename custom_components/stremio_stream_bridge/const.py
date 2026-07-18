"""Constants for Stremio Stream Bridge."""

from __future__ import annotations

DOMAIN = "stremio_stream_bridge"
NAME = "Stremio Stream Bridge"

CONF_STREAMING_SERVER_URL = "streaming_server_url"
CONF_CATALOG_MANIFEST_URLS = "catalog_manifest_urls"
CONF_STREAM_MANIFEST_URLS = "stream_manifest_urls"
CONF_SECONDARY_STREAM_MANIFEST_URL = "secondary_stream_manifest_url"
CONF_SUBTITLE_MANIFEST_URLS = "subtitle_manifest_urls"
CONF_LATIN_MANIFEST_URLS = "latin_manifest_urls"  # Legacy compatibility key.
CONF_SPORTS_MANIFEST_URLS = "sports_manifest_urls"
CONF_ADDON_MANIFEST_URL = "addon_manifest_url"  # Legacy v0.1 key.
CONF_DEFAULT_MEDIA_PLAYER = "default_media_player"
CONF_DEFAULT_STREAM_INDEX = "default_stream_index"  # Legacy v0.1 option.
CONF_PREFERRED_QUALITY = "preferred_quality"
CONF_MAX_SIZE_GB = "max_size_gb"
CONF_EXCLUDE_KEYWORDS = "exclude_keywords"
CONF_IDEAL_LINK_FILTER = "ideal_link_filter"
CONF_PREFER_H264 = "prefer_h264"
CONF_PREFER_SMALLER_SIZE = "prefer_smaller_size"
CONF_LATIN_AUDIO_KEYWORDS = "latin_audio_keywords"
CONF_HIDE_NON_LATIN_ITEMS = "hide_non_latin_items"
CONF_PREFERRED_AUDIO_LANGUAGES = "preferred_audio_languages"
CONF_CAST_COMPATIBILITY_FILTER = "cast_compatibility_filter"
CONF_STOP_BEFORE_PLAY = "stop_before_play"
CONF_CAST_RESET_BEFORE_PLAY = "cast_reset_before_play"
CONF_FALLBACK_ENABLED = "fallback_enabled"
CONF_FALLBACK_SOURCE_COUNT = "fallback_source_count"
CONF_PLAYBACK_START_TIMEOUT = "playback_start_timeout"
CONF_FAILURE_NOTIFY_HA = "failure_notify_ha"
CONF_TVOVERLAY_ENABLED = "tvoverlay_enabled"
CONF_TVOVERLAY_SERVICE = "tvoverlay_service"
CONF_TVOVERLAY_TARGET = "tvoverlay_target"
CONF_TVOVERLAY_DURATION = "tvoverlay_duration"
CONF_PLAY_IDEAL_ON_SELECT = "play_ideal_on_select"
CONF_AUDIO_MODE = "audio_mode"
CONF_SUBTITLE_MODE = "subtitle_mode"
CONF_SUBTITLE_LANGUAGES = "subtitle_languages"
CONF_SUBTITLE_CONVERT_VTT = "subtitle_convert_vtt"
CONF_SUBTITLE_BASE_URL = "subtitle_base_url"

DEFAULT_STREAMING_SERVER_URL = "http://192.168.1.145:11470"
DEFAULT_CINEMETA_MANIFEST = "https://v3-cinemeta.strem.io/manifest.json"
DEFAULT_TORRENTIO_MANIFEST = "https://torrentio.strem.fun/manifest.json"
DEFAULT_SECONDARY_STREAM_MANIFEST = ""
DEFAULT_OPENSUBTITLES_MANIFEST = "https://opensubtitles-v3.strem.io/manifest.json"
# Audio Latino now filters the main stream provider. Kept empty so new entries do
# not preload a second provider while older saved values remain harmlessly ignored.
DEFAULT_LATIN_MANIFEST = ""
DEFAULT_SPORTS_MANIFEST = "https://stremverse1.alwaysdata.net/manifest.json"
DEFAULT_PREFERRED_QUALITY = "1080p"
DEFAULT_MAX_SIZE_GB = 12.0
DEFAULT_EXCLUDE_KEYWORDS = "CAM, HDCAM, TS, TELECINE, SCREENER"
DEFAULT_IDEAL_LINK_FILTER = True
DEFAULT_PREFER_H264 = False
DEFAULT_PREFER_SMALLER_SIZE = False
DEFAULT_LATIN_AUDIO_KEYWORDS = (
    "audio latino, español latino, castellano latino, spanish latino, dual latino, "
    "latino, latina, latam, latinoamérica, latin america, español, castellano, spanish, "
    "🇦🇷, 🇧🇴, 🇨🇱, 🇨🇴, 🇨🇷, 🇪🇨, 🇲🇽, 🇵🇪, 🇺🇾, 🇻🇪"
)
DEFAULT_HIDE_NON_LATIN_ITEMS = True
DEFAULT_PREFERRED_AUDIO_LANGUAGES = "lat, esp, spa, es"
DEFAULT_CAST_COMPATIBILITY_FILTER = True
DEFAULT_STOP_BEFORE_PLAY = True
DEFAULT_CAST_RESET_BEFORE_PLAY = True
DEFAULT_FALLBACK_ENABLED = True
DEFAULT_FALLBACK_SOURCE_COUNT = 5
DEFAULT_PLAYBACK_START_TIMEOUT = 15
DEFAULT_FAILURE_NOTIFY_HA = True
DEFAULT_TVOVERLAY_ENABLED = False
DEFAULT_TVOVERLAY_SERVICE = "notify.tvoverlaynotify"
DEFAULT_TVOVERLAY_TARGET = ""
DEFAULT_TVOVERLAY_DURATION = 10
DEFAULT_PLAY_IDEAL_ON_SELECT = True
DEFAULT_AUDIO_MODE = "direct"
DEFAULT_SUBTITLE_MODE = "automatic"
DEFAULT_SUBTITLE_LANGUAGES = "spa, eng"
DEFAULT_SUBTITLE_CONVERT_VTT = True
DEFAULT_SUBTITLE_BASE_URL = ""
DEFAULT_SCAN_INTERVAL_SECONDS = 60

QUALITY_OPTIONS = ["auto", "2160p", "1080p", "720p", "480p", "lowest"]
AUDIO_MODE_OPTIONS = ["automatic", "direct", "force_transcode"]
SUBTITLE_MODE_OPTIONS = ["automatic", "disabled"]

PROFILE_DEFAULT = "default"
PROFILE_LATIN = "latin"
PROFILE_SPORTS = "sports"
PROFILE_OPTIONS = [PROFILE_DEFAULT, PROFILE_LATIN, PROFILE_SPORTS]

SERVICE_PLAY = "play"
SERVICE_PLAY_URL = "play_url"
SERVICE_REFRESH = "refresh"
SERVICE_SEARCH = "search"
SERVICE_RESOLVE = "resolve"
SERVICE_SUBTITLE_DIAGNOSTICS = "subtitle_diagnostics"

ATTR_ENTRY_ID = "entry_id"
ATTR_MEDIA_TYPE = "media_type"
ATTR_MEDIA_ID = "media_id"
ATTR_MEDIA_PLAYER = "media_player"
ATTR_STREAM_INDEX = "stream_index"
ATTR_URL = "url"
ATTR_QUERY = "query"
ATTR_DISABLE_SUBTITLES = "disable_subtitles"
ATTR_PROFILE = "profile"
ATTR_YEAR = "year"
ATTR_SEASON = "season"
ATTR_EPISODE = "episode"
ATTR_LIMIT = "limit"

PLATFORMS = ["binary_sensor"]
