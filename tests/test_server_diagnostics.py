"""GPU casting diagnostics tests."""

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
spec = spec_from_file_location("bridge_server_diagnostics_test", ROOT / "server_diagnostics.py")
assert spec is not None and spec.loader is not None
DIAGNOSTICS = module_from_spec(spec)
spec.loader.exec_module(DIAGNOSTICS)


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.response


class FakeServer:
    base_url = "http://127.0.0.1:11470/"

    def __init__(self, response):
        self._session = FakeSession(response)


def test_nvenc_diagnostics_report_hardware_ready() -> None:
    server = FakeServer(
        FakeResponse(
            200,
            {"selected_encoder": "h264_nvenc", "nvenc_usable": True},
        )
    )

    result = asyncio.run(DIAGNOSTICS.async_get_casting_diagnostics(server))

    assert server._session.urls == ["http://127.0.0.1:11470/casting/diagnostics"]
    assert result["hardware_ready"] is True


def test_missing_endpoint_is_optional() -> None:
    server = FakeServer(FakeResponse(404, {}))

    result = asyncio.run(DIAGNOSTICS.async_get_casting_diagnostics(server))

    assert result == {"available": False, "reason": "unsupported"}
