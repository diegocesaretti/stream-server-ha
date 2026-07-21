"""Synchronize Home Assistant playback position back to a linked Stremio account."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_ENTRY_ID,
    ATTR_MEDIA_ID,
    ATTR_MEDIA_PLAYER,
    ATTR_MEDIA_TYPE,
    CONF_DEFAULT_MEDIA_PLAYER,
    DOMAIN,
    SERVICE_PLAY,
)

_LOGGER = logging.getLogger(__name__)
_WRITE_INTERVAL = 60.0


@dataclass
class PlaybackSession:
    media_type: str
    media_id: str
    player: str
    resume_position: float = 0.0
    resume_applied: bool = False
    last_position: float = 0.0
    last_duration: float = 0.0
    last_write: float = 0.0


class StremioAccountPlaybackTracker:
    """Track one bridge entry's physical media player."""

    def __init__(self, hass: HomeAssistant, entry: Any, account_runtime: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.account_runtime = account_runtime
        self.session: PlaybackSession | None = None
        self._state_unsub = None
        self._service_unsub = hass.bus.async_listen(
            EVENT_CALL_SERVICE, self._handle_service_call
        )
        self._write_lock = asyncio.Lock()

    @callback
    def _handle_service_call(self, event: Event) -> None:
        data = event.data
        if data.get("domain") != DOMAIN or data.get("service") != SERVICE_PLAY:
            return
        service_data = data.get("service_data", {})
        if not isinstance(service_data, dict):
            return
        requested_entry = service_data.get(ATTR_ENTRY_ID)
        if requested_entry and requested_entry != self.entry.entry_id:
            return
        media_type = service_data.get(ATTR_MEDIA_TYPE)
        media_id = service_data.get(ATTR_MEDIA_ID)
        if not isinstance(media_type, str) or not isinstance(media_id, str):
            return
        player = service_data.get(ATTR_MEDIA_PLAYER) or self._default_player()
        if isinstance(player, str) and player:
            self.prepare_session(media_type, media_id, player)

    def prepare_session(
        self,
        media_type: str,
        media_id: str,
        player: str | None,
        *,
        resume_position: float = 0.0,
    ) -> None:
        """Start tracking a bridge playback before the physical player starts."""
        if not player:
            player = self._default_player()
        if not isinstance(player, str) or not player:
            return
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        self.session = PlaybackSession(
            media_type=media_type,
            media_id=media_id,
            player=player,
            resume_position=max(0.0, float(resume_position or 0.0)),
        )
        self._state_unsub = async_track_state_change_event(
            self.hass, [player], self._handle_player_state
        )

    @callback
    def _handle_player_state(self, event: Event) -> None:
        session = self.session
        new_state = event.data.get("new_state")
        if session is None or new_state is None:
            return
        if event.data.get("entity_id") != session.player:
            return
        position, duration = _player_times(new_state)
        if position > 0:
            session.last_position = position
        if duration > 0:
            session.last_duration = duration
        state = str(new_state.state).lower()
        if (
            state == "playing"
            and session.resume_position >= 15
            and not session.resume_applied
        ):
            session.resume_applied = True
            self.hass.async_create_task(self._apply_resume(session))
        now = time.monotonic()
        terminal = state in {"paused", "idle", "off", "standby", "unavailable"}
        due = now - session.last_write >= _WRITE_INTERVAL
        if session.last_position > 0 and (terminal or due):
            session.last_write = now
            self.hass.async_create_task(self._write_progress(session))

    async def _apply_resume(self, session: PlaybackSession) -> None:
        await asyncio.sleep(1)
        if self.session is not session:
            return
        try:
            await self.hass.services.async_call(
                "media_player",
                "media_seek",
                {
                    "entity_id": session.player,
                    "seek_position": session.resume_position,
                },
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001 - optional resume must not break playback.
            _LOGGER.debug("Could not apply Stremio resume position: %s", err)

    async def _write_progress(self, session: PlaybackSession) -> None:
        if self.session is not session:
            return
        async with self._write_lock:
            try:
                updated = await self.account_runtime.client.async_update_progress(
                    media_type=session.media_type,
                    media_id=session.media_id,
                    position_seconds=session.last_position,
                    duration_seconds=session.last_duration,
                )
                if updated:
                    _update_local_snapshot(
                        self.account_runtime.coordinator,
                        session.media_type,
                        session.media_id,
                        session.last_position,
                        session.last_duration,
                    )
            except Exception as err:  # noqa: BLE001 - account sync is non-fatal.
                _LOGGER.warning("Could not update Stremio playback progress: %s", err)

    def _default_player(self) -> str | None:
        current = {**self.entry.data, **self.entry.options}
        player = current.get(CONF_DEFAULT_MEDIA_PLAYER)
        return str(player) if player else None

    async def async_stop(self) -> None:
        """Remove listeners and flush the last known position."""
        session = self.session
        if session is not None and session.last_position > 0:
            await self._write_progress(session)
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        if self._service_unsub is not None:
            self._service_unsub()
            self._service_unsub = None
        self.session = None


def _player_times(state: Any) -> tuple[float, float]:
    attrs = state.attributes if isinstance(state.attributes, dict) else {}
    position = _float(attrs.get("media_position"))
    duration = _float(attrs.get("media_duration"))
    updated = attrs.get("media_position_updated_at")
    if position > 0 and str(state.state).lower() == "playing" and isinstance(updated, datetime):
        now = datetime.now(timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        position += max(0.0, (now - updated).total_seconds())
    if duration > 0:
        position = min(position, duration)
    return position, duration


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _update_local_snapshot(
    coordinator: Any,
    media_type: str,
    media_id: str,
    position: float,
    duration: float,
) -> None:
    data = coordinator.data
    if not isinstance(data, dict):
        return
    base_id = media_id.split(":", 1)[0]
    changed = False
    for key in ("library", "continue_watching"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") != media_type or item.get("media_id") != base_id:
                continue
            item["playback_id"] = media_id
            item["position"] = position
            item["duration"] = duration
            item["progress_percent"] = (
                round(position / duration * 100, 1) if duration > 0 else 0.0
            )
            changed = True
    if changed:
        coordinator.async_set_updated_data(data)
