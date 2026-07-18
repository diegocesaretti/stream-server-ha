"""Tests for the public voice and automation content resolver."""

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_content_resolver_test"
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


CONST = load("const")
RESOLVER = load("resolver")


MOVIES = [
    {
        "id": "tt0133093",
        "type": "movie",
        "name": "The Matrix",
        "releaseInfo": "1999",
        "poster": "https://image.example/matrix.jpg",
        "background": "https://image.example/matrix-bg.jpg",
        "description": "A simulated world.",
        "_bridge_media_type": "movie",
        "_bridge_catalog_addon": "Cinemeta",
        "_bridge_addon_url": "https://private.example/manifest.json",
    }
]

DUNES = [
    {
        "id": "tt0087182",
        "name": "Dune",
        "year": 1984,
        "_bridge_media_type": "movie",
    },
    {
        "id": "tt1160419",
        "name": "Dune",
        "released": "2021-10-22T00:00:00.000Z",
        "_bridge_media_type": "movie",
    },
]

SERIES_META = {
    "id": "tt0903747",
    "name": "Breaking Bad",
    "releaseInfo": "2008–2013",
    "poster": "https://image.example/bb.jpg",
    "background": "https://image.example/bb-bg.jpg",
    "description": "A chemistry teacher changes careers.",
    "videos": [
        {
            "id": "tt0903747:1:1",
            "season": 1,
            "episode": 1,
            "title": "Pilot",
            "thumbnail": "https://image.example/pilot.jpg",
        },
        {
            "id": "tt0903747:2:1",
            "season": "2",
            "episode": "1",
            "name": "Seven Thirty-Seven",
        },
        {
            "id": "tt0903747:2:3",
            "season": 2,
            "episode": 3,
            "title": "Bit by a Dead Bee",
            "released": "2009-03-22",
        },
        {"id": None, "season": 2, "episode": 4, "title": "Malformed"},
    ],
}


class FakeManager:
    def __init__(self, results, metas=None, *, search_error=None, meta_error=None):
        self.results = list(results)
        self.metas = metas or {}
        self.search_error = search_error
        self.meta_error = meta_error
        self.search_calls = []
        self.meta_calls = []

    async def search(self, query, media_types):
        self.search_calls.append((query, media_types))
        if self.search_error:
            raise self.search_error
        return list(self.results)

    async def get_meta(self, media_type, media_id, profile=CONST.PROFILE_DEFAULT):
        self.meta_calls.append((media_type, media_id, profile))
        if self.meta_error:
            raise self.meta_error
        return self.metas[(media_type, media_id)]


def resolve(manager, **kwargs):
    return asyncio.run(RESOLVER.async_resolve_content(manager, **kwargs))


def test_title_normalization_removes_case_punctuation_and_accents():
    assert RESOLVER.normalize_title("  El NIÑO: ¡Acción! 2 ") == "el nino accion 2"


def test_exact_movie_match_returns_public_metadata_only():
    result = resolve(FakeManager(MOVIES, {("movie", "tt0133093"): MOVIES[0]}), query="The Matrix")
    assert result["status"] == "exact"
    assert result["selected"]["media_id"] == "tt0133093"
    assert result["selected"]["year"] == 1999
    assert "_bridge_catalog_addon" not in result["selected"]
    assert "_bridge_addon_url" not in result["selected"]


def test_requested_year_disambiguates_same_title():
    result = resolve(FakeManager(DUNES, {("movie", "tt1160419"): DUNES[1]}), query="Dune", media_type="movie", year=2021)
    assert result["status"] == "exact"
    assert result["selected"]["media_id"] == "tt1160419"


def test_same_title_without_year_is_ambiguous():
    result = resolve(FakeManager(DUNES), query="Dune", media_type="movie")
    assert result["status"] == "ambiguous"
    assert result["selected"] is None
    assert [item["year"] for item in result["results"]] == [1984, 2021]


def test_unrelated_provider_results_are_treated_as_not_found():
    manager = FakeManager(
        [{"id": "tt1", "name": "Completely Different", "_bridge_media_type": "movie"}]
    )
    result = resolve(manager, query="titulo absolutamente inexistente 928371")
    assert result["status"] == "not_found"
    assert result["results"] == []


def test_series_without_episode_returns_available_seasons():
    search = [{"id": "tt0903747", "name": "Breaking Bad", "_bridge_media_type": "series"}]
    result = resolve(
        FakeManager(search, {("series", "tt0903747"): SERIES_META}),
        query="Breaking Bad",
        media_type="series",
    )
    assert result["status"] == "series_needs_episode"
    assert result["selected"]["available_seasons"] == [1, 2]
    assert result["available_seasons"] == [1, 2]


def test_series_with_season_returns_available_episodes():
    search = [{"id": "tt0903747", "name": "Breaking Bad", "_bridge_media_type": "series"}]
    result = resolve(
        FakeManager(search, {("series", "tt0903747"): SERIES_META}),
        query="Breaking Bad",
        media_type="series",
        season=2,
    )
    assert result["status"] == "series_needs_episode"
    assert result["requested_season"] == 2
    assert [item["episode"] for item in result["available_episodes"]] == [1, 3]


def test_specific_episode_resolves_real_video_id():
    search = [{"id": "tt0903747", "name": "Breaking Bad", "_bridge_media_type": "series"}]
    result = resolve(
        FakeManager(search, {("series", "tt0903747"): SERIES_META}),
        query="Breaking Bad",
        media_type="series",
        season=2,
        episode=3,
        profile="latin",
    )
    assert result["status"] == "exact"
    assert result["profile"] == "latin"
    assert result["selected"] == {
        "media_id": "tt0903747:2:3",
        "media_type": "series",
        "series_id": "tt0903747",
        "series_title": "Breaking Bad",
        "title": "Bit by a Dead Bee",
        "year": 2009,
        "season": 2,
        "episode": 3,
        "poster": "https://image.example/bb.jpg",
        "background": "https://image.example/bb-bg.jpg",
        "description": "A chemistry teacher changes careers.",
    }


def test_nonexistent_season_returns_episode_not_found():
    search = [{"id": "tt0903747", "name": "Breaking Bad", "_bridge_media_type": "series"}]
    result = resolve(
        FakeManager(search, {("series", "tt0903747"): SERIES_META}),
        query="Breaking Bad",
        media_type="series",
        season=9,
        episode=1,
    )
    assert result["status"] == "episode_not_found"
    assert result["available_seasons"] == [1, 2]


def test_nonexistent_episode_returns_available_season_episodes():
    search = [{"id": "tt0903747", "name": "Breaking Bad", "_bridge_media_type": "series"}]
    result = resolve(
        FakeManager(search, {("series", "tt0903747"): SERIES_META}),
        query="Breaking Bad",
        media_type="series",
        season=2,
        episode=99,
    )
    assert result["status"] == "episode_not_found"
    assert [item["episode"] for item in result["available_episodes"]] == [1, 3]


def test_incomplete_metadata_keeps_stable_null_fields():
    public = RESOLVER.normalize_public_result(
        {"id": "tt1", "name": "Minimal", "_bridge_media_type": "movie"}
    )
    assert set(public) == {
        "media_id",
        "media_type",
        "title",
        "year",
        "poster",
        "background",
        "description",
    }
    assert public["year"] is None
    assert public["poster"] is None


def test_ambiguous_results_honor_maximum_limit():
    results = [
        {"id": f"tt{index}", "name": f"Dune {index}", "_bridge_media_type": "movie"}
        for index in range(20)
    ]
    result = resolve(FakeManager(results), query="Dune", limit=10)
    assert result["status"] == "ambiguous"
    assert len(result["results"]) == 10


def test_search_still_stores_raw_results_and_returns_public_response():
    manager = FakeManager(MOVIES)
    runtime = types.SimpleNamespace(
        manager=manager,
        last_search_query=None,
        last_search_results=[],
    )
    response = asyncio.run(RESOLVER.async_search_and_store(runtime, " Matrix ", "all"))
    assert runtime.last_search_query == "Matrix"
    assert runtime.last_search_results == MOVIES
    assert response["count"] == 1
    assert response["results"][0]["media_id"] == "tt0133093"
    assert "_bridge_catalog_addon" not in response["results"][0]


def test_sports_profile_is_structured_unsupported_result():
    result = resolve(FakeManager([]), query="Formula 1", profile="sports")
    assert result["ok"] is False
    assert result["status"] == "unsupported"


def test_provider_error_is_structured_and_does_not_leak_details():
    result = resolve(
        FakeManager([], search_error=RuntimeError("https://secret.example/token")),
        query="Matrix",
    )
    assert result["ok"] is False
    assert result["status"] == "error"
    assert "secret" not in result["error"]
