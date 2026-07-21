"""Focused tests for the optional Stremio account layer."""

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_account_hybrid_test"

pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg

try:
    import aiohttp  # noqa: F401
except ImportError:
    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientSession:
        pass

    class ClientTimeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    aiohttp.ClientError = ClientError
    aiohttp.ClientSession = ClientSession
    aiohttp.ClientTimeout = ClientTimeout
    sys.modules["aiohttp"] = aiohttp

api = types.ModuleType(f"{PACKAGE}.api")


class StremioConnectionError(Exception):
    pass


class StremioProtocolError(Exception):
    pass


api.StremioConnectionError = StremioConnectionError
api.StremioProtocolError = StremioProtocolError
sys.modules[api.__name__] = api

spec = spec_from_file_location(f"{PACKAGE}.account_client", ROOT / "account_client.py")
assert spec is not None and spec.loader is not None
ACCOUNT = module_from_spec(spec)
sys.modules[spec.name] = ACCOUNT
spec.loader.exec_module(ACCOUNT)


def test_normalize_library_item_uses_time_offset_milliseconds() -> None:
    item = {
        "_id": "series:tt1234567",
        "type": "series",
        "name": "Example",
        "state": {
            "timeOffset": 502_732,
            "timeWatched": 47_210,
            "duration": 3_233_275,
            "video_id": "tt1234567:2:3",
        },
    }
    normalized = ACCOUNT.normalize_library_item(item)
    assert normalized["position"] == 502.732
    assert normalized["duration"] == 3233.275
    assert normalized["playback_id"] == "tt1234567:2:3"
    assert normalized["season"] == 2
    assert normalized["episode"] == 3


def test_addon_descriptor_never_exposes_private_transport_url() -> None:
    secret = "https://addon.example/token-very-secret/manifest.json"
    descriptor = ACCOUNT.addon_descriptor(
        {
            "transportUrl": secret,
            "manifest": {
                "id": "example",
                "name": "Private add-on",
                "version": "1.0.0",
                "resources": ["catalog", "stream", "subtitles"],
                "catalogs": [{"type": "movie", "id": "top"}],
            },
        }
    )
    assert descriptor is not None
    assert descriptor["transport_url"] == secret
    assert secret not in descriptor["safe_url"]
    assert descriptor["safe_url"].startswith("account://")
    assert descriptor["roles"] == {"catalog", "stream", "subtitle"}


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return {"success": True}


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json))
        return FakeResponse()


def test_progress_update_preserves_item_and_counts_real_advance() -> None:
    session = FakeSession()
    client = ACCOUNT.StremioAccountClient(
        session, email="diego@example.com", auth_key="secret-auth-key"
    )
    original = {
        "_id": "series:tt1234567",
        "type": "series",
        "name": "Example",
        "state": {
            "timeOffset": 1_000,
            "timeWatched": 55_000,
            "duration": 100_000,
            "video_id": "tt1234567:2:3",
            "customField": "preserve-me",
        },
    }
    client._raw_library = [original]

    updated = asyncio.run(
        client.async_update_progress(
            media_type="series",
            media_id="tt1234567:2:3",
            position_seconds=12.5,
            duration_seconds=100,
        )
    )

    assert updated is True
    _, request = session.calls[-1]
    assert request["authKey"] == "secret-auth-key"
    changed = request["changes"][0]
    assert changed["state"]["timeOffset"] == 12_500
    assert changed["state"]["duration"] == 100_000
    assert changed["state"]["video_id"] == "tt1234567:2:3"
    assert changed["state"]["season"] == 2
    assert changed["state"]["episode"] == 3
    assert changed["state"]["timeWatched"] == 66_500
    assert changed["state"]["overallTimeWatched"] == 11_500
    assert changed["state"]["customField"] == "preserve-me"
    assert original["state"]["video_id"] == "tt1234567:2:3"
