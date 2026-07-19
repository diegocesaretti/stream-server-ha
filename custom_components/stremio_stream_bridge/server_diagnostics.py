"""Optional diagnostics for GPU-enabled stream-server builds."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout

_LOGGER = logging.getLogger(__name__)
_DIAGNOSTICS_TIMEOUT = ClientTimeout(total=10)


async def async_get_casting_diagnostics(server: Any) -> dict[str, Any]:
    """Read ``/casting/diagnostics`` without making older servers unhealthy."""
    url = f"{server.base_url}casting/diagnostics"
    try:
        async with server._session.get(url, timeout=_DIAGNOSTICS_TIMEOUT) as response:
            if response.status == 404:
                return {"available": False, "reason": "unsupported"}
            if response.status >= 400:
                return {
                    "available": False,
                    "reason": f"HTTP {response.status}",
                }
            payload = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError, AttributeError, TypeError) as err:
        _LOGGER.debug("GPU casting diagnostics unavailable at %s: %s", url, err)
        return {"available": False, "reason": str(err)}

    if not isinstance(payload, dict):
        return {"available": False, "reason": "invalid response"}

    selected_encoder = payload.get("selected_encoder")
    nvenc_usable = payload.get("nvenc_usable")
    result = dict(payload)
    result["available"] = True
    result["hardware_ready"] = (
        selected_encoder == "h264_nvenc" and nvenc_usable is True
    )
    return result
