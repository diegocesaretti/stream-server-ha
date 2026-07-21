"""Optional Stremio account client for library, add-ons and progress sync."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .api import StremioConnectionError, StremioProtocolError

_API_BASE = "https://api.strem.io"
_LOGIN_URL = f"{_API_BASE}/api/login"
_USER_URL = f"{_API_BASE}/api/getUser"
_DATASTORE_GET_URL = f"{_API_BASE}/api/datastoreGet"
_DATASTORE_PUT_URL = f"{_API_BASE}/api/datastorePut"
_ADDON_COLLECTION_URL = f"{_API_BASE}/api/addonCollectionGet"
_TIMEOUT = ClientTimeout(total=30)
_LIBRARY_COLLECTION = "libraryItem"


def utc_iso_ms() -> str:
    """Return the timestamp format used by Stremio's datastore."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def account_url_id(url: str) -> str:
    """Return a stable non-secret identifier for a private add-on URL."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"account://{digest}"


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    return result if isinstance(result, dict) else payload


def _library_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", [])
    if not isinstance(result, list):
        raise StremioProtocolError("Stremio library response is not a list")
    return [item for item in result if isinstance(item, dict)]


def normalize_library_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw Stremio library item without exposing account internals."""
    raw_id = str(item.get("_id") or "")
    media_type = str(item.get("type") or "movie")
    base_id = raw_id.split(":", 1)[1] if ":" in raw_id else raw_id
    state = item.get("state") if isinstance(item.get("state"), dict) else {}
    video_id = str(state.get("video_id") or base_id)
    position_ms = _as_number(state.get("timeOffset"), state.get("timeWatched"), 0)
    duration_ms = _as_number(state.get("duration"), 0)
    season = _as_optional_int(state.get("season"))
    episode = _as_optional_int(state.get("episode"))
    if media_type == "series" and video_id.count(":") >= 2:
        parts = video_id.split(":")
        season = season if season is not None else _as_optional_int(parts[-2])
        episode = episode if episode is not None else _as_optional_int(parts[-1])
    progress = (position_ms / duration_ms * 100) if duration_ms > 0 else 0.0
    return {
        "library_id": raw_id,
        "media_id": base_id,
        "playback_id": video_id or base_id,
        "type": media_type,
        "title": str(item.get("name") or base_id or "Unknown"),
        "poster": item.get("poster"),
        "background": item.get("background"),
        "year": item.get("year"),
        "removed": bool(item.get("removed", False)),
        "position": max(0.0, position_ms / 1000.0),
        "duration": max(0.0, duration_ms / 1000.0),
        "progress_percent": round(max(0.0, min(progress, 100.0)), 1),
        "season": season,
        "episode": episode,
        "last_watched": state.get("lastWatched"),
        "finished": bool(state.get("flaggedWatched")) or progress >= 90.0,
    }


def _as_number(*values: object) -> float:
    for value in values:
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _as_optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and str(value) != "" else None
    except (TypeError, ValueError):
        return None


def addon_descriptor(addon: dict[str, Any]) -> dict[str, Any] | None:
    """Return safe metadata and protocol roles for an account add-on."""
    manifest = addon.get("manifest")
    transport_url = addon.get("transportUrl") or addon.get("transport_url")
    if not isinstance(manifest, dict) or not isinstance(transport_url, str):
        return None
    resources = manifest.get("resources", [])
    names = {
        str(resource if isinstance(resource, str) else resource.get("name") or "")
        for resource in resources
        if isinstance(resource, (str, dict))
    }
    roles: set[str] = set()
    if manifest.get("catalogs") or "catalog" in names or "meta" in names:
        roles.add("catalog")
    if "stream" in names:
        roles.add("stream")
    if "subtitles" in names:
        roles.add("subtitle")
    if not roles:
        return None
    return {
        "transport_url": transport_url,
        "safe_url": account_url_id(transport_url),
        "id": str(manifest.get("id") or account_url_id(transport_url)),
        "name": str(manifest.get("name") or manifest.get("id") or "Account add-on"),
        "version": manifest.get("version"),
        "roles": roles,
        "manifest": manifest,
    }


class StremioAccountClient:
    """Small authenticated client for the Stremio account API."""

    def __init__(
        self,
        session: ClientSession,
        *,
        email: str = "",
        auth_key: str = "",
    ) -> None:
        self._session = session
        self.email = email.strip()
        self.auth_key = auth_key.strip()
        self.user_id: str | None = None
        self._raw_library: list[dict[str, Any]] = []
        self._raw_addons: list[dict[str, Any]] = []

    async def async_login(self, password: str) -> str:
        """Authenticate once and retain only the resulting auth key."""
        if not self.email or not password:
            raise StremioProtocolError("Stremio email and password are required")
        payload = await self._post(
            _LOGIN_URL,
            {"email": self.email, "password": password, "facebook": False},
            authenticated=False,
        )
        data = _result(payload)
        auth_key = payload.get("authKey") or data.get("authKey")
        user = payload.get("user") if isinstance(payload.get("user"), dict) else data
        if not isinstance(auth_key, str) or not auth_key:
            raise StremioProtocolError("Stremio login did not return an auth key")
        self.auth_key = auth_key
        self.user_id = str(user.get("_id") or "") or None
        return auth_key

    async def async_get_user(self) -> dict[str, Any]:
        payload = await self._post(_USER_URL, {})
        data = _result(payload)
        self.user_id = str(data.get("_id") or self.user_id or "") or None
        return {"email": self.email, "user_id": self.user_id}

    async def async_get_library_raw(self) -> list[dict[str, Any]]:
        payload = await self._post(
            _DATASTORE_GET_URL,
            {"collection": _LIBRARY_COLLECTION, "all": True, "ids": []},
        )
        self._raw_library = _library_items(payload)
        return copy.deepcopy(self._raw_library)

    async def async_get_addon_collection(self) -> list[dict[str, Any]]:
        payload = await self._post(_ADDON_COLLECTION_URL, {"update": True})
        data = _result(payload)
        addons = payload.get("addons") or data.get("addons") or []
        if not isinstance(addons, list):
            raise StremioProtocolError("Stremio add-on collection is not a list")
        self._raw_addons = [addon for addon in addons if isinstance(addon, dict)]
        return copy.deepcopy(self._raw_addons)

    async def async_snapshot(self) -> dict[str, Any]:
        """Fetch account metadata, library and installed add-ons."""
        user = await self.async_get_user()
        raw_library = await self.async_get_library_raw()
        raw_addons = await self.async_get_addon_collection()
        library = [
            normalized
            for item in raw_library
            if not (normalized := normalize_library_item(item))["removed"]
        ]
        continue_watching = sorted(
            (
                item
                for item in library
                if item["position"] > 0
                and item["duration"] > 0
                and not item["finished"]
            ),
            key=lambda item: str(item.get("last_watched") or ""),
            reverse=True,
        )
        descriptors = [
            descriptor
            for addon in raw_addons
            if (descriptor := addon_descriptor(addon)) is not None
        ]
        return {
            "user": user,
            "library": library,
            "continue_watching": continue_watching,
            "addons": [
                {
                    "id": descriptor["id"],
                    "name": descriptor["name"],
                    "version": descriptor["version"],
                    "roles": sorted(descriptor["roles"]),
                    "source": descriptor["safe_url"],
                }
                for descriptor in descriptors
            ],
            "library_count": len(library),
            "continue_watching_count": len(continue_watching),
            "addon_count": len(descriptors),
        }

    @property
    def raw_addons(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._raw_addons)

    async def async_update_progress(
        self,
        *,
        media_type: str,
        media_id: str,
        position_seconds: float,
        duration_seconds: float,
    ) -> bool:
        """Write the physical player's resume position back to Stremio."""
        if not self._raw_library:
            await self.async_get_library_raw()
        base_id = media_id.split(":", 1)[0]
        target_id = f"{media_type}:{base_id}"
        source = next(
            (
                item
                for item in self._raw_library
                if str(item.get("_id") or "") == target_id
                or str(item.get("_id") or "").endswith(f":{base_id}")
            ),
            None,
        )
        if source is None:
            return False
        updated = copy.deepcopy(source)
        state = updated.setdefault("state", {})
        if not isinstance(state, dict):
            state = {}
            updated["state"] = state
        position_ms = max(0, int(position_seconds * 1000))
        reported_duration_ms = max(0, int(duration_seconds * 1000))
        existing_duration_ms = max(0, int(_as_number(state.get("duration"), 0)))
        duration_ms = max(reported_duration_ms, existing_duration_ms)
        previous_video_id = str(state.get("video_id") or "")
        previous_offset_ms = max(0, int(_as_number(state.get("timeOffset"), 0)))
        time_watched_ms = max(0, int(_as_number(state.get("timeWatched"), 0)))
        overall_watched_ms = max(
            0, int(_as_number(state.get("overallTimeWatched"), 0))
        )
        if previous_video_id and previous_video_id != media_id:
            overall_watched_ms += time_watched_ms
            time_watched_ms = 0
            previous_offset_ms = position_ms
            state["flaggedWatched"] = 0
        elif position_ms > previous_offset_ms:
            # Cap one polling delta so a forward seek is not counted as watched time.
            delta_ms = min(position_ms - previous_offset_ms, 120_000)
            time_watched_ms += delta_ms
            overall_watched_ms += delta_ms
        now = utc_iso_ms()
        state["timeOffset"] = position_ms
        if duration_ms > 0:
            state["duration"] = duration_ms
        state["timeWatched"] = time_watched_ms
        state["overallTimeWatched"] = overall_watched_ms
        state["lastWatched"] = now
        state["video_id"] = media_id
        if duration_ms > 0 and time_watched_ms >= duration_ms * 0.9:
            if not bool(state.get("flaggedWatched")):
                state["timesWatched"] = max(
                    0, int(_as_number(state.get("timesWatched"), 0))
                ) + 1
            state["flaggedWatched"] = 1
        if media_type == "series" and media_id.count(":") >= 2:
            parts = media_id.split(":")
            state["season"] = _as_optional_int(parts[-2]) or 0
            state["episode"] = _as_optional_int(parts[-1]) or 0
        updated["_mtime"] = now
        updated["removed"] = False
        await self._post(
            _DATASTORE_PUT_URL,
            {"collection": _LIBRARY_COLLECTION, "changes": [updated]},
        )
        self._raw_library = [
            updated if item is source else item for item in self._raw_library
        ]
        return True

    async def _post(
        self,
        url: str,
        data: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        payload = dict(data)
        if authenticated:
            if not self.auth_key:
                raise StremioProtocolError("Stremio account is not authenticated")
            payload["authKey"] = self.auth_key
        try:
            async with self._session.post(url, json=payload, timeout=_TIMEOUT) as response:
                if response.status in {401, 403}:
                    raise StremioProtocolError("Stremio account authentication failed")
                if response.status >= 400:
                    raise StremioConnectionError(
                        f"Stremio account request failed with HTTP {response.status}"
                    )
                result = await response.json(content_type=None)
        except StremioProtocolError:
            raise
        except (ClientError, TimeoutError, ValueError) as err:
            raise StremioConnectionError(f"Stremio account request failed: {err}") from err
        if not isinstance(result, dict):
            raise StremioProtocolError("Stremio account response is not an object")
        return result
