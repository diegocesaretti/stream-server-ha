"""Seed-health ranking and low-power stream-server policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
import sys
from typing import Any

from .const import (
    CONF_AUDIO_MODE,
    CONF_LOW_POWER_STREAM_SERVER,
    DEFAULT_AUDIO_MODE,
    DEFAULT_LOW_POWER_STREAM_SERVER,
)

_LOGGER = logging.getLogger(__name__)
_MIN_SEEDERS_MARKER = "_bridge_min_torrent_seeders"
_LOW_POWER_MARKER = "_bridge_low_power_stream_server"


def _is_torrent_stream(stream: Mapping[str, Any]) -> bool:
    """Return whether a Stremio stream is backed by a torrent."""
    raw_url = str(stream.get("url") or "")
    return bool(stream.get("infoHash")) or raw_url.startswith("magnet:")


def _minimum_seeders(streams: Sequence[Mapping[str, Any]]) -> int:
    """Read the entry-scoped soft minimum carried by enriched streams."""
    values: list[int] = []
    for stream in streams:
        try:
            values.append(max(0, int(stream.get(_MIN_SEEDERS_MARKER, 0) or 0)))
        except (TypeError, ValueError):
            continue
    return max(values, default=0)


def _seed_health_rank(stream: Mapping[str, Any], minimum: int, parse_seeders) -> int:
    """Rank healthy torrents before weak and unknown torrents."""
    if minimum <= 0 or not _is_torrent_stream(stream):
        return 0
    seeders = parse_seeders(dict(stream))
    if seeders >= minimum:
        return 0
    if seeders > 0:
        return 1
    return 2


def _apply_seed_policy(
    ordered: Sequence[dict[str, Any]],
    *,
    prefer_direct_play: bool,
    parse_seeders,
    compatibility_rank,
) -> list[dict[str, Any]]:
    """Apply a soft minimum while preserving direct-play compatibility tiers."""
    candidates = list(ordered)
    minimum = _minimum_seeders(candidates)
    if minimum <= 0 or len(candidates) < 2:
        return candidates

    def compatibility(stream: dict[str, Any]) -> tuple[Any, ...]:
        return compatibility_rank(stream) if prefer_direct_play else ()

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for stream in candidates:
        grouped.setdefault(compatibility(stream), []).append(stream)

    kept_ids: set[int] = set()
    for group in grouped.values():
        healthy_torrent = any(
            _is_torrent_stream(stream) and parse_seeders(stream) >= minimum
            for stream in group
        )
        for stream in group:
            if (
                not healthy_torrent
                or not _is_torrent_stream(stream)
                or parse_seeders(stream) >= minimum
            ):
                kept_ids.add(id(stream))

    filtered = [stream for stream in candidates if id(stream) in kept_ids]
    original_position = {id(stream): index for index, stream in enumerate(filtered)}
    return sorted(
        filtered,
        key=lambda stream: (
            *compatibility(stream),
            _seed_health_rank(stream, minimum, parse_seeders),
            original_position[id(stream)],
        ),
    )


def effective_playback_options(options: Mapping[str, Any]) -> Mapping[str, Any]:
    """Force direct playback when the stream-server cannot transcode."""
    if not bool(
        options.get(CONF_LOW_POWER_STREAM_SERVER, DEFAULT_LOW_POWER_STREAM_SERVER)
    ):
        return options
    if str(options.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE)) != "force_transcode":
        return options
    adjusted = dict(options)
    adjusted[CONF_AUDIO_MODE] = "direct"
    return adjusted


def install_source_policy_patch() -> None:
    """Patch imported ranking call sites and the playback preparation function once."""
    from . import playback, stream_selector

    if getattr(stream_selector, "_bridge_seed_policy_patched", False):
        return

    original_order = stream_selector.order_ideal_streams

    def order_ideal_streams(
        streams: list[dict[str, Any]],
        max_size_gb: float,
        exclude_keywords: str,
        *,
        preferred_quality: str = "1080p",
        prefer_direct_play: bool = False,
        strict_compatibility: bool = False,
        prefer_h264: bool | None = None,
        prefer_smaller_size: bool | None = None,
    ) -> list[dict[str, Any]]:
        ordered = original_order(
            streams,
            max_size_gb,
            exclude_keywords,
            preferred_quality=preferred_quality,
            prefer_direct_play=prefer_direct_play,
            strict_compatibility=strict_compatibility,
            prefer_h264=prefer_h264,
            prefer_smaller_size=prefer_smaller_size,
        )
        return _apply_seed_policy(
            ordered,
            prefer_direct_play=prefer_direct_play,
            parse_seeders=stream_selector.parse_seeders,
            compatibility_rank=stream_selector.direct_play_compatibility_rank,
        )

    def choose_ideal_stream(
        streams: list[dict[str, Any]],
        max_size_gb: float,
        exclude_keywords: str,
        *,
        prefer_h264: bool | None = None,
        prefer_smaller_size: bool | None = None,
    ) -> dict[str, Any]:
        ordered = order_ideal_streams(
            streams,
            max_size_gb,
            exclude_keywords,
            prefer_h264=prefer_h264,
            prefer_smaller_size=prefer_smaller_size,
        )
        if not ordered:
            raise ValueError("No streams satisfy the configured filters or maximum size")
        return ordered[0]

    def choose_best_stream(
        streams: list[dict[str, Any]],
        preferred_quality: str,
        max_size_gb: float,
        exclude_keywords: str,
        *,
        prefer_h264: bool | None = None,
        prefer_smaller_size: bool | None = None,
    ) -> dict[str, Any]:
        ordered = order_ideal_streams(
            streams,
            max_size_gb,
            exclude_keywords,
            preferred_quality=preferred_quality,
            prefer_h264=prefer_h264,
            prefer_smaller_size=prefer_smaller_size,
        )
        if not ordered:
            raise ValueError("No streams satisfy the configured filters or maximum size")
        return ordered[0]

    original_prepare_playback = playback.prepare_playback

    def prepare_playback(
        server,
        stream: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        profile: str,
        cast_target: bool = False,
    ):
        adjusted = effective_playback_options(options)
        if adjusted is not options:
            _LOGGER.debug(
                "Low-power stream-server mode disabled hlsv2 transcoding for this source"
            )
        return original_prepare_playback(
            server,
            stream,
            adjusted,
            profile=profile,
            cast_target=cast_target,
        )

    stream_selector.order_ideal_streams = order_ideal_streams
    stream_selector.choose_ideal_stream = choose_ideal_stream
    stream_selector.choose_best_stream = choose_best_stream
    playback.prepare_playback = prepare_playback
    stream_selector._bridge_seed_policy_patched = True

    package_name = __package__ or "custom_components.stremio_stream_bridge"
    for module_name in (package_name, f"{package_name}.media_source"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "order_ideal_streams"):
            module.order_ideal_streams = order_ideal_streams
        if hasattr(module, "choose_ideal_stream"):
            module.choose_ideal_stream = choose_ideal_stream
        if hasattr(module, "choose_best_stream"):
            module.choose_best_stream = choose_best_stream


def install_runtime_source_policy(
    manager: Any,
    *,
    min_torrent_seeders: int,
    low_power_stream_server: bool,
) -> None:
    """Annotate streams with entry-scoped ranking and server capability settings."""
    policy = getattr(manager, "_bridge_runtime_source_policy", None)
    if isinstance(policy, dict):
        policy["min_torrent_seeders"] = max(0, int(min_torrent_seeders))
        policy["low_power_stream_server"] = bool(low_power_stream_server)
        return

    policy = {
        "min_torrent_seeders": max(0, int(min_torrent_seeders)),
        "low_power_stream_server": bool(low_power_stream_server),
    }
    original_get_streams = manager.get_streams

    async def get_streams(*args, **kwargs):
        streams = await original_get_streams(*args, **kwargs)
        enriched: list[dict[str, Any]] = []
        for stream in streams:
            item = dict(stream)
            item[_MIN_SEEDERS_MARKER] = policy["min_torrent_seeders"]
            item[_LOW_POWER_MARKER] = policy["low_power_stream_server"]
            if policy["low_power_stream_server"]:
                item["_bridge_force_transcode"] = False
            enriched.append(item)
        return enriched

    manager.get_streams = get_streams
    manager._bridge_runtime_source_policy = policy
