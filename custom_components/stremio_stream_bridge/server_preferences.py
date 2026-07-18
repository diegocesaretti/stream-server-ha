"""Pass preferred audio-track metadata to compatible stream-server builds."""

from __future__ import annotations

from collections.abc import Iterable
from types import MethodType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .const import DEFAULT_PREFERRED_AUDIO_LANGUAGES


def parse_audio_languages(value: object) -> tuple[str, ...]:
    """Parse ordered language codes such as ``lat, esp, spa, es``."""
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        raw = ",".join(str(item) for item in value)
    else:
        raw = str(value or "")
    for separator in (";", "\n"):
        raw = raw.replace(separator, ",")
    return tuple(
        dict.fromkeys(
            part.strip().casefold()
            for part in raw.split(",")
            if part.strip()
        )
    )


def install_preferred_audio_languages(server: Any, value: object) -> tuple[str, ...]:
    """Append an ordered ``audioLanguages`` query parameter to hlsv2 URLs.

    Older stream-server builds safely ignore the extra query parameter. The GPU
    build uses it to mark the first matching internal audio track as the HLS
    default, falling back to the file's original default track when no match exists.
    """
    languages = parse_audio_languages(value)
    if not languages:
        languages = parse_audio_languages(DEFAULT_PREFERRED_AUDIO_LANGUAGES)

    state = getattr(server, "_bridge_audio_language_state", None)
    if isinstance(state, dict):
        state["languages"] = languages
        return languages

    original = server.build_compatible_hls_url
    state = {"languages": languages}

    def build_compatible_hls_url(
        self,
        media_url: str,
        *,
        force_transcoding: bool = False,
        max_audio_channels: int = 2,
    ) -> str:
        url = original(
            media_url,
            force_transcoding=force_transcoding,
            max_audio_channels=max_audio_channels,
        )
        preferred = state["languages"]
        if not preferred:
            return url
        parsed = urlsplit(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query = [(key, item) for key, item in query if key != "audioLanguages"]
        query.append(("audioLanguages", ",".join(preferred)))
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    server._bridge_audio_language_state = state
    server.build_compatible_hls_url = MethodType(build_compatible_hls_url, server)
    return languages
