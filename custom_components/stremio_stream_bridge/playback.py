"""Prepare player-compatible media URLs and validate automatic candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from typing import Any

from .api import (
    StremioBridgeError,
    StremioStreamServerClient,
    guess_stream_mime_type,
)
from .const import (
    CONF_AUDIO_MODE,
    DEFAULT_AUDIO_MODE,
    PROFILE_SPORTS,
)

_LOGGER = logging.getLogger(__name__)
_HLS_MIME = "application/vnd.apple.mpegurl"
_INCOMPATIBLE_AUDIO_MARKERS = (
    "dts",
    "truehd",
    "eac3",
    "e-ac-3",
    "ddp",
    "dolby digital plus",
    "ac3",
    "ac-3",
    "7.1",
)


def _stream_text(stream: Mapping[str, Any]) -> str:
    hints = stream.get("behaviorHints")
    filename = hints.get("filename") if isinstance(hints, Mapping) else None
    return " ".join(
        str(value).lower()
        for value in (
            stream.get("name"),
            stream.get("title"),
            stream.get("description"),
            filename,
        )
        if value
    )


def needs_compatible_hls(stream: Mapping[str, Any], resolved_url: str) -> bool:
    """Return whether the stream is likely to need AAC/HLS compatibility."""
    lowered_url = resolved_url.lower().split("?", 1)[0]
    if lowered_url.endswith((".m3u8", ".mpd")):
        return False
    if stream.get("infoHash"):
        return True
    text = _stream_text(stream)
    if text.endswith((".mkv", ".avi")) or ".mkv" in text or ".avi" in text:
        return True
    return any(marker in text for marker in _INCOMPATIBLE_AUDIO_MARKERS)


def prepare_playback(
    server: StremioStreamServerClient,
    stream: Mapping[str, Any],
    options: Mapping[str, Any],
    *,
    profile: str,
) -> tuple[str, str]:
    """Resolve a stream and optionally route it through hlsv2 for AAC audio."""
    resolved_url = server.resolve_stream(stream)
    mode = str(options.get(CONF_AUDIO_MODE, DEFAULT_AUDIO_MODE))
    if mode == "direct":
        return resolved_url, guess_stream_mime_type(stream, resolved_url)

    # Existing HLS/DASH feeds should stay as supplied. Wrapping live playlists in
    # hlsv2 can break tokens, Referer headers and relative segment URLs.
    force = mode == "force_transcode"
    should_wrap = force or (
        profile != PROFILE_SPORTS and needs_compatible_hls(stream, resolved_url)
    )
    if should_wrap:
        return (
            server.build_compatible_hls_url(
                resolved_url,
                force_transcoding=force,
                max_audio_channels=2,
            ),
            _HLS_MIME,
        )
    return resolved_url, guess_stream_mime_type(stream, resolved_url)


async def prepare_first_playable(
    server: StremioStreamServerClient,
    candidates: Sequence[dict[str, Any]],
    options: Mapping[str, Any],
    *,
    profile: str,
) -> tuple[dict[str, Any], str, str]:
    """Resolve ranked candidates and skip dead proxied playlists."""
    if not candidates:
        raise StremioBridgeError("No stream candidates are available")

    failures: list[str] = []
    for position, stream in enumerate(candidates):
        try:
            url, mime_type = prepare_playback(server, stream, options, profile=profile)
        except StremioBridgeError as err:
            failures.append(str(err))
            continue

        valid, reason = await server.async_validate_media_url(url, mime_type)
        if valid:
            if position:
                _LOGGER.info(
                    "Selected fallback stream %s after %s rejected candidate(s)",
                    position + 1,
                    position,
                )
            _LOGGER.debug("Prepared stream URL %s with MIME %s", url, mime_type)
            return stream, url, mime_type

        failures.append(reason or "playlist validation failed")
        _LOGGER.warning(
            "Skipping unavailable automatic stream candidate %s: %s",
            position + 1,
            reason or "validation failed",
        )

    detail = "; ".join(failures[-3:])
    raise StremioBridgeError(
        "All automatically selected stream links failed validation"
        + (f": {detail}" if detail else "")
    )
