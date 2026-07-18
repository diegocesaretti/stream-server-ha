"""Tests for Latin Audio filtering through the main stream provider."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_latin_filter_test"

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

STREAM_MANIFEST = {
    "id": "main-streams",
    "name": "Main Streams",
    "types": ["movie", "series"],
    "resources": [
        {"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]}
    ],
    "catalogs": [],
}

LEGACY_LATIN_MANIFEST = {
    "id": "legacy-latin",
    "name": "Legacy Latin",
    "types": ["movie"],
    "resources": [{"name": "stream", "types": ["movie"], "idPrefixes": ["tt"]}],
    "catalogs": [],
}


class FakeClient:
    def __init__(self, url, manifest, streams=None):
        self.manifest_url = url
        self._manifest = manifest
        self._streams = streams or {}
        self.manifest_calls = 0
        self.stream_calls = 0

    async def get_manifest(self):
        self.manifest_calls += 1
        return self._manifest

    async def get_streams(self, media_type, media_id):
        self.stream_calls += 1
        return self._streams.get((media_type, media_id), [])


def test_release_metadata_recognizes_latin_audio_markers():
    assert AGG.stream_has_latin_audio({"title": "Movie.1080p.x264.LATINO"})
    assert AGG.stream_has_latin_audio({"description": "Audio Español Latino 5.1"})
    assert AGG.stream_has_latin_audio(
        {"behaviorHints": {"filename": "Movie.Spanish.Latino.WEB-DL.mkv"}}
    )
    assert AGG.stream_has_latin_audio({"name": "🇲🇽 Movie 1080p"})
    assert not AGG.stream_has_latin_audio({"title": "Movie 1080p English"})
    assert not AGG.stream_has_latin_audio({"title": "Anime Dual Audio ENG JPN"})


@pytest.mark.asyncio
async def test_latin_profile_filters_main_provider_and_ignores_legacy_provider():
    main = FakeClient(
        "https://main/manifest.json",
        STREAM_MANIFEST,
        {
            ("movie", "tt1"): [
                {"title": "Movie 1080p English", "url": "https://video/english"},
                {"title": "Movie 1080p x264 Latino", "url": "https://video/latino"},
            ]
        },
    )
    legacy = FakeClient(
        "https://legacy/manifest.json",
        LEGACY_LATIN_MANIFEST,
        {
            ("movie", "tt1"): [
                {"title": "Legacy source Latino", "url": "https://legacy/latino"}
            ]
        },
    )
    manager = AGG.StremioAddonManager([], [main], [], [legacy], [])
    await manager.async_refresh()

    streams = await manager.get_streams("movie", "tt1", "latin")

    assert [stream["url"] for stream in streams] == ["https://video/latino"]
    assert streams[0]["_bridge_addon_name"] == "Main Streams"
    assert main.manifest_calls == 1
    assert main.stream_calls == 1
    assert legacy.manifest_calls == 0
    assert legacy.stream_calls == 0
    assert manager.has_profile("latin")


@pytest.mark.asyncio
async def test_latin_profile_does_not_fallback_to_non_latin_audio():
    main = FakeClient(
        "https://main/manifest.json",
        STREAM_MANIFEST,
        {
            ("movie", "tt1"): [
                {"title": "Movie 1080p English", "url": "https://video/english"}
            ]
        },
    )
    manager = AGG.StremioAddonManager([], [main])
    await manager.async_refresh()

    with pytest.raises(AGG.StremioProtocolError, match="Latin Audio keywords"):
        await manager.get_streams("movie", "tt1", "latin")


@pytest.mark.asyncio
async def test_default_profile_keeps_all_main_provider_sources():
    main = FakeClient(
        "https://main/manifest.json",
        STREAM_MANIFEST,
        {
            ("movie", "tt1"): [
                {"title": "Movie 1080p English", "url": "https://video/english"},
                {"title": "Movie 1080p Latino", "url": "https://video/latino"},
            ]
        },
    )
    manager = AGG.StremioAddonManager([], [main])
    await manager.async_refresh()

    streams = await manager.get_streams("movie", "tt1", "default")

    assert [stream["url"] for stream in streams] == [
        "https://video/english",
        "https://video/latino",
    ]
