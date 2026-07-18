from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_media_search_test"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg

api = types.ModuleType(f"{PACKAGE}.api")


class StremioBridgeError(Exception):
    pass


class StremioProtocolError(Exception):
    pass


api.StremioAddonClient = object
api.StremioBridgeError = StremioBridgeError
api.StremioProtocolError = StremioProtocolError
sys.modules[api.__name__] = api

const = types.ModuleType(f"{PACKAGE}.const")
const.PROFILE_DEFAULT = "default"
const.PROFILE_LATIN = "latin"
const.PROFILE_SPORTS = "sports"
sys.modules[const.__name__] = const

spec = spec_from_file_location(f"{PACKAGE}.aggregator", ROOT / "aggregator.py")
assert spec is not None and spec.loader is not None
AGG = module_from_spec(spec)
sys.modules[spec.name] = AGG
spec.loader.exec_module(AGG)


class FakeClient:
    def __init__(self, url, manifest, results=None, error=False):
        self.manifest_url = url
        self._manifest = manifest
        self._results = results or []
        self._error = error
        self.calls = []

    async def get_manifest(self):
        return self._manifest

    async def get_catalog(self, media_type, catalog_id, extra=None):
        self.calls.append((media_type, catalog_id, extra))
        if self._error:
            raise RuntimeError("provider failed")
        return list(self._results)


def manifest(name, media_type="movie", catalog_id="top"):
    return {
        "id": name.casefold(),
        "name": name,
        "resources": ["catalog"],
        "types": [media_type],
        "catalogs": [
            {
                "type": media_type,
                "id": catalog_id,
                "extraSupported": ["search"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_search_queries_every_capable_catalog_and_deduplicates():
    first = FakeClient(
        "https://one/manifest.json",
        manifest("One"),
        [
            {"id": "tt1", "name": "Matrix Reloaded"},
            {"id": "tt2", "name": "The Matrix"},
        ],
    )
    second = FakeClient(
        "https://two/manifest.json",
        manifest("Two", catalog_id="movies"),
        [
            {"id": "tt2", "name": "The Matrix"},
            {"id": "tt3", "name": "Matrix Resurrections"},
        ],
    )
    manager = AGG.StremioAddonManager([first, second], [])
    await manager.async_refresh()

    results = await manager.search(" Matrix ", ("movie",))

    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert first.calls[0][2] == {"search": "Matrix"}
    assert [item["id"] for item in results] == ["tt2", "tt1", "tt3"]
    assert results[0]["_bridge_catalog_addon"] == "One"


@pytest.mark.asyncio
async def test_search_ignores_one_failed_provider():
    failed = FakeClient(
        "https://failed/manifest.json",
        manifest("Failed"),
        error=True,
    )
    working = FakeClient(
        "https://working/manifest.json",
        manifest("Working", catalog_id="movies"),
        [{"id": "tt1", "name": "The Matrix"}],
    )
    manager = AGG.StremioAddonManager([failed, working], [])
    await manager.async_refresh()

    results = await manager.search("Matrix", ("movie",))

    assert [item["id"] for item in results] == ["tt1"]


@pytest.mark.asyncio
async def test_search_blank_query_does_not_call_providers():
    client = FakeClient(
        "https://one/manifest.json",
        manifest("One"),
        [{"id": "tt1", "name": "The Matrix"}],
    )
    manager = AGG.StremioAddonManager([client], [])
    await manager.async_refresh()

    assert await manager.search("   ", ("movie",)) == []
    assert client.calls == []


@pytest.mark.asyncio
async def test_search_limits_results_to_fifty():
    client = FakeClient(
        "https://one/manifest.json",
        manifest("One"),
        [{"id": f"tt{index}", "name": f"Result {index}"} for index in range(80)],
    )
    manager = AGG.StremioAddonManager([client], [])
    await manager.async_refresh()

    results = await manager.search("Result", ("movie",))

    assert len(results) == 50
