"""Tests for v0.4 provider profiles, audio compatibility and Cast styling."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_v04_test"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg


def load(name: str):
    spec = spec_from_file_location(f"{PACKAGE}.{name}", ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


API = load("api")
AGG = load("aggregator")
PLAYBACK = load("playback")
STYLE = load("cast_style")
CONST = load("const")


class FakeClient:
    def __init__(self, url, manifest, *, streams=None):
        self.manifest_url = url
        self.base_url = url.removesuffix("/manifest.json")
        self._manifest = manifest
        self._streams = streams or {}

    async def get_manifest(self):
        return self._manifest

    async def get_catalog(self, media_type, catalog_id, extra=None):
        return []

    async def get_meta(self, media_type, media_id):
        return {"id": media_id, "name": media_id}

    async def get_streams(self, media_type, media_id):
        return self._streams.get((media_type, media_id), [])

    async def get_subtitles(self, media_type, media_id, extra=None):
        return []


CATALOG = {
    "id": "catalog",
    "name": "Catalog",
    "resources": ["catalog", "meta"],
    "types": ["movie", "series"],
    "catalogs": [{"type": "movie", "id": "top", "name": "Popular"}],
}
LATIN = {
    "id": "latin",
    "name": "Latino",
    "resources": [{"name": "stream", "types": ["movie", "series"]}],
    "types": ["movie", "series"],
    "catalogs": [],
}
SPORTS = {
    "id": "sports",
    "name": "Sports",
    "resources": ["catalog", "meta", "stream"],
    "types": ["tv"],
    "catalogs": [{"type": "tv", "id": "live", "name": "Live"}],
}


@pytest.mark.asyncio
async def test_latin_profile_mirrors_default_catalog_and_uses_only_latin_streams():
    catalog = FakeClient("https://catalog/manifest.json", CATALOG)
    latin = FakeClient(
        "https://latin/manifest.json",
        LATIN,
        streams={("movie", "tt1"): [{"url": "https://video.example/latino.mp4"}]},
    )
    manager = AGG.StremioAddonManager([catalog], [], latin_clients=[latin])
    await manager.async_refresh()
    assert manager.catalogs("movie", CONST.PROFILE_LATIN)[0][1]["id"] == "top"
    streams = await manager.get_streams("movie", "tt1", CONST.PROFILE_LATIN)
    assert streams[0]["_bridge_addon_name"] == "Latino"


@pytest.mark.asyncio
async def test_sports_profile_uses_own_catalog():
    sports = FakeClient("https://sports/manifest.json", SPORTS)
    manager = AGG.StremioAddonManager([], [], sports_clients=[sports])
    await manager.async_refresh()
    assert manager.catalogs("tv", CONST.PROFILE_SPORTS)[0][1]["id"] == "live"


def test_automatic_audio_mode_wraps_torrent_as_h264_aac_hls():
    server = API.StremioStreamServerClient(object(), "http://server:11470")
    stream = {
        "infoHash": "0123456789abcdef0123456789abcdef01234567",
        "fileIdx": 0,
        "behaviorHints": {"filename": "movie.mkv"},
    }
    url, mime = PLAYBACK.prepare_playback(
        server,
        stream,
        {CONST.CONF_AUDIO_MODE: "automatic"},
        profile=CONST.PROFILE_DEFAULT,
    )
    assert "/hlsv2/" in url
    assert "audioCodecs=aac" in url
    assert "videoCodecs=h264" in url
    assert mime == "application/vnd.apple.mpegurl"


def test_sports_hls_is_not_wrapped_twice():
    server = API.StremioStreamServerClient(object(), "http://server:11470")
    stream = {"url": "https://sports.example/live.m3u8"}
    url, mime = PLAYBACK.prepare_playback(
        server,
        stream,
        {CONST.CONF_AUDIO_MODE: "automatic"},
        profile=CONST.PROFILE_SPORTS,
    )
    assert url == "https://sports.example/live.m3u8"
    assert mime == "application/vnd.apple.mpegurl"


def test_cast_subtitle_style_removes_black_outline_and_window():
    message = {
        "type": "LOAD",
        "media": {
            "tracks": [{"trackId": 1}],
            "textTrackStyle": {"edgeType": "OUTLINE", "edgeColor": "#000000FF"},
        },
    }
    STYLE.remove_subtitle_edges(message)
    style = message["media"]["textTrackStyle"]
    assert style["edgeType"] == "NONE"
    assert style["edgeColor"] == "#00000000"
    assert style["windowType"] == "NONE"


def test_force_transcode_audio_mode_sets_force_flag():
    server = API.StremioStreamServerClient(object(), "http://server:11470")
    stream = {"url": "https://video.example/movie.mp4"}
    url, mime = PLAYBACK.prepare_playback(
        server,
        stream,
        {CONST.CONF_AUDIO_MODE: "force_transcode"},
        profile=CONST.PROFILE_DEFAULT,
    )
    assert "/hlsv2/" in url
    assert "forceTranscoding=1" in url
    assert "audioCodecs=aac" in url
    assert mime == "application/vnd.apple.mpegurl"


def test_v041_user_specific_defaults():
    assert CONST.DEFAULT_STREAMING_SERVER_URL == "http://192.168.1.145:11470"
    assert CONST.DEFAULT_LATIN_MANIFEST == "https://cinecalidad-stremio-addon.fly.dev/manifest.json"
    assert CONST.DEFAULT_SPORTS_MANIFEST == "https://stremverse1.alwaysdata.net/manifest.json"


@pytest.mark.asyncio
async def test_optional_provider_failure_does_not_discard_working_core_addons():
    class FailingClient(FakeClient):
        async def get_manifest(self):
            raise API.StremioConnectionError("optional provider offline")

    catalog = FakeClient("https://catalog/manifest.json", CATALOG)
    default_stream = FakeClient("https://stream/manifest.json", LATIN)
    failing_latin = FailingClient("https://latin/manifest.json", LATIN)
    manager = AGG.StremioAddonManager(
        [catalog],
        [default_stream],
        latin_clients=[failing_latin],
    )
    addons = await manager.async_refresh()
    assert len(addons) == 2
    assert manager.catalogs("movie")
    assert manager.errors["https://latin/manifest.json"] == "optional provider offline"
