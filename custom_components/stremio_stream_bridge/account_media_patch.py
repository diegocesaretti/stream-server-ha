"""Expose linked-account library and resume items in the existing media source."""

from __future__ import annotations

from typing import Any

from .account_bridge import get_account_runtime
from .const import PROFILE_DEFAULT

_PATCH_ATTR = "_bridge_account_media_patched"


def install_account_media_patch() -> None:
    """Patch account folders into the established media browser and resolver."""
    from . import media_source

    cls = media_source.StremioBridgeMediaSource
    if getattr(cls, _PATCH_ATTR, False):
        return
    original_browse_media = cls.async_browse_media
    original_browse_entry = cls._browse_entry
    original_build_stream_choices = cls._build_stream_choices
    original_resolve_media = cls.async_resolve_media

    async def async_browse_media(self, item):
        if item.identifier:
            try:
                payload = media_source._decode(item.identifier)
            except Exception:  # noqa: BLE001 - let the original method report it.
                payload = {}
            kind = payload.get("kind")
            if kind in {"account_library", "account_continue"}:
                return _browse_account_collection(self, media_source, payload)
        return await original_browse_media(self, item)

    def _browse_entry(self, payload):
        node = original_browse_entry(self, payload)
        account = get_account_runtime(self.hass, str(payload["entry_id"]))
        if account is None:
            return node
        children = list(getattr(node, "children", None) or [])
        account_nodes = [
            media_source._node(
                identifier=media_source._encode(
                    {"kind": "account_continue", "entry_id": payload["entry_id"]}
                ),
                media_class=media_source.MediaClass.DIRECTORY,
                media_content_type=media_source.MediaType.VIDEO,
                title="Continuar viendo",
                can_play=False,
                can_expand=True,
                children_media_class=media_source.MediaClass.VIDEO,
            ),
            media_source._node(
                identifier=media_source._encode(
                    {"kind": "account_library", "entry_id": payload["entry_id"]}
                ),
                media_class=media_source.MediaClass.DIRECTORY,
                media_content_type=media_source.MediaType.VIDEO,
                title="Mi biblioteca de Stremio",
                can_play=False,
                can_expand=True,
                children_media_class=media_source.MediaClass.VIDEO,
            ),
        ]
        _set_attr(node, "children", [*account_nodes, *children])
        return node

    def _build_stream_choices(self, payload, streams):
        node = original_build_stream_choices(self, payload, streams)
        resume_position = _float(payload.get("resume_position"))
        if resume_position <= 0:
            return node
        for child in list(getattr(node, "children", None) or []):
            identifier = getattr(child, "identifier", None)
            if not identifier:
                continue
            try:
                child_payload = media_source._decode(identifier)
            except Exception:  # noqa: BLE001 - unrelated child identifier.
                continue
            if child_payload.get("kind") != "video":
                continue
            child_payload["resume_position"] = resume_position
            _set_attr(child, "identifier", media_source._encode(child_payload))
        return node

    async def async_resolve_media(self, item):
        payload: dict[str, Any] = {}
        if item.identifier:
            try:
                payload = media_source._decode(item.identifier)
            except Exception:  # noqa: BLE001 - original resolver handles invalid ids.
                payload = {}
        if payload.get("kind") == "video":
            account = get_account_runtime(self.hass, str(payload.get("entry_id") or ""))
            if account is not None and account.tracker is not None:
                account.tracker.prepare_session(
                    str(payload.get("type") or "movie"),
                    str(payload.get("id") or ""),
                    item.target_media_player,
                    resume_position=_float(payload.get("resume_position")),
                )
        return await original_resolve_media(self, item)

    cls.async_browse_media = async_browse_media
    cls._browse_entry = _browse_entry
    cls._build_stream_choices = _build_stream_choices
    cls.async_resolve_media = async_resolve_media
    setattr(cls, _PATCH_ATTR, True)


def _browse_account_collection(self, media_source, payload: dict[str, Any]):
    entry_id = str(payload["entry_id"])
    account = get_account_runtime(self.hass, entry_id)
    if account is None:
        raise media_source.BrowseError("No Stremio account is linked to this entry")
    data = account.coordinator.data or {}
    is_continue = payload.get("kind") == "account_continue"
    source_items = data.get("continue_watching" if is_continue else "library", [])
    if not isinstance(source_items, list):
        source_items = []
    items = source_items if is_continue else sorted(
        source_items, key=lambda value: str(value.get("title") or "").casefold()
    )
    children = [
        _account_item_node(self, media_source, entry_id, item, is_continue)
        for item in items
        if isinstance(item, dict)
    ]
    return media_source._node(
        identifier=media_source._encode(payload),
        media_class=media_source.MediaClass.DIRECTORY,
        media_content_type=media_source.MediaType.VIDEO,
        title="Continuar viendo" if is_continue else "Mi biblioteca de Stremio",
        can_play=False,
        can_expand=True,
        children_media_class=media_source.MediaClass.VIDEO,
        children=children,
    )


def _account_item_node(self, media_source, entry_id: str, item: dict[str, Any], resume: bool):
    media_type = str(item.get("type") or "movie")
    base_id = str(item.get("media_id") or "")
    playback_id = str(item.get("playback_id") or base_id)
    title = str(item.get("title") or base_id or "Unknown")
    poster = item.get("poster") or item.get("background")
    position = _float(item.get("position")) if resume else 0.0
    progress = _float(item.get("progress_percent"))
    season = item.get("season")
    episode = item.get("episode")
    display_title = title
    if resume:
        details = []
        if media_type == "series" and season is not None and episode is not None:
            details.append(f"T{int(season)} E{int(episode)}")
        if progress > 0:
            details.append(f"{progress:.0f}%")
        if details:
            display_title = f"{title} · {' · '.join(details)}"

    direct = resume or (media_type != "series" and self._direct_play_enabled(self._entry(entry_id)))
    selected_id = playback_id if resume else base_id
    if direct:
        identifier = media_source._encode(
            {
                "kind": "video",
                "entry_id": entry_id,
                "type": media_type,
                "profile": PROFILE_DEFAULT,
                "id": selected_id,
                "selection": "auto",
                "name": title,
                "poster": poster,
                "resume_position": position,
            }
        )
    else:
        identifier = media_source._encode(
            {
                "kind": "meta",
                "entry_id": entry_id,
                "type": media_type,
                "profile": PROFILE_DEFAULT,
                "id": selected_id,
                "name": title,
                "poster": poster,
                "resume_position": position,
            }
        )
    if media_type == "series" and resume:
        media_class = media_source.MediaClass.EPISODE
        content_type = media_source.MediaType.EPISODE
    elif media_type == "series":
        media_class = media_source.MediaClass.TV_SHOW
        content_type = media_source.MediaType.TVSHOW
    else:
        media_class = media_source.MediaClass.MOVIE
        content_type = media_source.MediaType.MOVIE
    return media_source._node(
        identifier=identifier,
        media_class=media_class,
        media_content_type=content_type,
        title=display_title,
        can_play=direct,
        can_expand=not direct,
        thumbnail=poster,
        children_media_class=None if direct else media_source.MediaClass.VIDEO,
    )


def _set_attr(target: Any, name: str, value: Any) -> None:
    try:
        setattr(target, name, value)
    except (AttributeError, TypeError):
        object.__setattr__(target, name, value)


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0
