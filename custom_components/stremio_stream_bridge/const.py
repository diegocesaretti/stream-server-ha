"""Constants for Stremio Stream Bridge."""

from __future__ import annotations

DOMAIN = "stremio_stream_bridge"
NAME = "Stremio Stream Bridge"

CONF_STREAMING_SERVER_URL = "streaming_server_url"
CONF_CATALOG_MANIFEST_URLS = "catalog_manifest_urls"
CONF_STREAM_MANIFEST_URLS = "stream_manifest_urls"
CONF_SUBTITLE_MANIFEST_URLS = "subtitle_manifest_urls"
CONF_ADDON_MANIFEST_URL = "addon_manifest_url"  # Legacy v0.1 key.
CONF_DEFAULT_MEDIA_PLAYER = "default_media_player"
CONF_DEFAULT_STREAM_INDEX = "default_stream_index"  # Legacy v0.1 option.
CONF_PREFERRED_QUALITY = "preferred_quality"
CONF_MAX_SIZE_GB = "max_size_gb"
CONF_EXCLUDE_KEYWORDS = "exclude_keywords"
CONF_IDEAL_LINK_FILTER = "ideal_link_filter"
CONF_SUBTITLE_MODE = "subtitle_mode"
CONF_SUBTITLE_LANGUAGES = "subtitle_languages"
CONF_SUBTITLE_CONVERT_VTT = "subtitle_convert_vtt"

DEFAULT_CINEMETA_MANIFEST = "https://v3-cinemeta.strem.io/manifest.json"
DEFAULT_TORRENTIO_MANIFEST = "https://torrentio.strem.fun/manifest.json"
DEFAULT_OPENSUBTITLES_MANIFEST = "https://opensubtitles-v3.strem.io/manifest.json"
DEFAULT_PREFERRED_QUALITY = "1080p"
DEFAULT_MAX_SIZE_GB = 12.0
DEFAULT_EXCLUDE_KEYWORDS = "CAM, HDCAM, TS, TELECINE, SCREENER"
DEFAULT_IDEAL_LINK_FILTER = True
DEFAULT_SUBTITLE_MODE = "automatic"
DEFAULT_SUBTITLE_LANGUAGES = "spa, eng"
DEFAULT_SUBTITLE_CONVERT_VTT = True
DEFAULT_SCAN_INTERVAL_SECONDS = 60

QUALITY_OPTIONS = ["auto", "2160p", "1080p", "720p", "480p", "lowest"]
SUBTITLE_MODE_OPTIONS = ["automatic", "disabled"]

SERVICE_PLAY = "play"
SERVICE_PLAY_URL = "play_url"
SERVICE_REFRESH = "refresh"
SERVICE_SEARCH = "search"

ATTR_ENTRY_ID = "entry_id"
ATTR_MEDIA_TYPE = "media_type"
ATTR_MEDIA_ID = "media_id"
ATTR_MEDIA_PLAYER = "media_player"
ATTR_STREAM_INDEX = "stream_index"
ATTR_URL = "url"
ATTR_QUERY = "query"
ATTR_DISABLE_SUBTITLES = "disable_subtitles"

PLATFORMS = ["binary_sensor"]
