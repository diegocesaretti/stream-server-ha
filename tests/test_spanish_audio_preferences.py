"""Spanish/Latin release filtering and catalog visibility tests."""

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_spanish_audio_test"

pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg

aggregator = types.ModuleType(f"{PACKAGE}.aggregator")
aggregator.LoadedAddon = object
sys.modules[aggregator.__name__] = aggregator

api = types.ModuleType(f"{PACKAGE}.api")


class StremioBridgeError(Exception):
    pass


class StremioProtocolError(StremioBridgeError):
    pass


api.StremioBridgeError = StremioBridgeError
api.StremioProtocolError = StremioProtocolError
sys.modules[api.__name__] = api

const = types.ModuleType(f"{PACKAGE}.const")
const.DEFAULT_HIDE_NON_LATIN_ITEMS = True
const.DEFAULT_LATIN_AUDIO_KEYWORDS = (
    "audio latino, español latino, castellano, spanish, latino, latam"
)
const.DEFAULT_PREFER_H264 = False
const.DEFAULT_PREFER_SMALLER_SIZE = False
const.PROFILE_DEFAULT = "default"
const.PROFILE_LATIN = "latin"
sys.modules[const.__name__] = const

spec = spec_from_file_location(f"{PACKAGE}.source_preferences", ROOT / "source_preferences.py")
assert spec is not None and spec.loader is not None
PREFERENCES = module_from_spec(spec)
sys.modules[spec.name] = PREFERENCES
spec.loader.exec_module(PREFERENCES)


class FakeManager:
    def __init__(self, streams: list[dict] | None = None) -> None:
        self._streams = streams or []

    async def get_streams(self, media_type: str, media_id: str, profile: str) -> list[dict]:
        return list(self._streams)

    def catalogs(self, media_type=None, profile="default"):
        return []

    def get_addon(self, manifest_url: str):
        raise AssertionError(manifest_url)

    async def get_meta(self, media_type: str, media_id: str, profile: str):
        return {"videos": []}


def test_release_matching_ignores_accents_and_punctuation() -> None:
    item = {
        "title": "Movie.1080p.DUAL-ESPAÑOL-LATINO.x265",
        "behaviorHints": {"filename": "movie.mkv"},
    }
    keywords = PREFERENCES.parse_audio_keywords("espanol latino, castellano")

    assert PREFERENCES.stream_has_spanish_audio(item, keywords)


def test_release_matching_uses_all_supported_fields() -> None:
    keywords = PREFERENCES.parse_audio_keywords("latam")
    item = {
        "name": "Provider",
        "description": "Audio: LATAM",
        "behaviorHints": {"filename": "movie.1080p.mkv"},
    }

    assert PREFERENCES.stream_has_spanish_audio(item, keywords)


def test_audio_track_codes_are_not_implicitly_torrent_keywords() -> None:
    item = {"title": "A harmless title with the word estate"}
    keywords = PREFERENCES.parse_audio_keywords("latino, español")

    assert not PREFERENCES.stream_has_spanish_audio(item, keywords)


def test_latin_profile_filters_main_provider_streams() -> None:
    manager = FakeManager(
        [
            {"title": "Movie 1080p English", "url": "https://example/english"},
            {"title": "Movie 1080p Audio Latino", "url": "https://example/latino"},
        ]
    )
    preferences = PREFERENCES.SourcePreferences(manager)
    preferences.configure(latin_audio_keywords="audio latino")

    streams = asyncio.run(preferences.get_streams("movie", "tt1", "latin"))

    assert [stream["url"] for stream in streams] == ["https://example/latino"]
    assert streams[0]["_bridge_prefer_h264"] is False
    assert streams[0]["_bridge_prefer_smaller_size"] is False


def test_latin_profile_reports_confirmed_no_match() -> None:
    manager = FakeManager([{"title": "Movie English", "url": "https://example/en"}])
    preferences = PREFERENCES.SourcePreferences(manager)
    preferences.configure(latin_audio_keywords="audio latino")

    with pytest.raises(PREFERENCES.SpanishAudioSourceNotFound):
        asyncio.run(preferences.get_streams("movie", "tt1", "latin"))


def test_catalog_filter_hides_only_confirmed_false_results() -> None:
    manager = FakeManager()
    preferences = PREFERENCES.SourcePreferences(manager)
    metas = [{"id": "yes"}, {"id": "no"}, {"id": "unknown"}]

    async def availability(media_type: str, meta: dict):
        return {"yes": True, "no": False, "unknown": None}[meta["id"]]

    preferences._safe_availability = availability
    filtered = asyncio.run(preferences.filter_catalog(metas, "movie"))

    assert [meta["id"] for meta in filtered] == ["yes", "unknown"]


def test_series_sampling_uses_start_middle_and_end() -> None:
    values = [f"episode-{index}" for index in range(10)]

    assert PREFERENCES.representative_ids(values, 3) == [
        "episode-0",
        "episode-5",
        "episode-9",
    ]
