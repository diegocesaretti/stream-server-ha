"""Entry-scoped source preferences and Spanish/Latin catalog filtering."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import unicodedata

from .aggregator import LoadedAddon
from .api import StremioBridgeError, StremioProtocolError
from .const import (
    DEFAULT_HIDE_NON_LATIN_ITEMS,
    DEFAULT_LATIN_AUDIO_KEYWORDS,
    DEFAULT_PREFER_H264,
    DEFAULT_PREFER_SMALLER_SIZE,
    PROFILE_DEFAULT,
    PROFILE_LATIN,
)

_LOGGER = logging.getLogger(__name__)
_CACHE_SECONDS = 30 * 60
_CATALOG_CONCURRENCY = 6
_SERIES_SAMPLE_COUNT = 3


class SpanishAudioSourceNotFound(StremioProtocolError):
    """Raised when providers respond but none advertises configured audio."""


class _FilteredCatalogClient:
    """Proxy one catalog and hide entries without a matching audio source."""

    def __init__(self, preferences: "SourcePreferences", source: Any) -> None:
        self._preferences = preferences
        self._source = source
        self.manifest_url = f"{source.manifest_url}#bridge-audio-es"
        self.base_url = source.base_url

    async def get_catalog(
        self,
        media_type: str,
        catalog_id: str,
        extra: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        metas = await self._source.get_catalog(media_type, catalog_id, extra)
        return await self._preferences.filter_catalog(metas, media_type)


class SourcePreferences:
    """Decorate one Stremio manager with entry-specific source behavior."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self._original_get_streams = manager.get_streams
        self._original_catalogs = manager.catalogs
        self._original_get_addon = manager.get_addon
        self.prefer_h264 = DEFAULT_PREFER_H264
        self.prefer_smaller_size = DEFAULT_PREFER_SMALLER_SIZE
        self.force_transcode = False
        self.keywords = parse_audio_keywords(DEFAULT_LATIN_AUDIO_KEYWORDS)
        self.hide_non_matching = DEFAULT_HIDE_NON_LATIN_ITEMS
        self._catalog_addons: dict[str, LoadedAddon] = {}
        self._availability_cache: dict[tuple[str, str], tuple[float, bool]] = {}
        self._probe_semaphore: asyncio.Semaphore | None = None

    def configure(
        self,
        *,
        prefer_h264: bool = DEFAULT_PREFER_H264,
        prefer_smaller_size: bool = DEFAULT_PREFER_SMALLER_SIZE,
        latin_audio_keywords: object = DEFAULT_LATIN_AUDIO_KEYWORDS,
        hide_non_latin_items: bool = DEFAULT_HIDE_NON_LATIN_ITEMS,
        force_transcode: bool = False,
    ) -> None:
        """Update preferences and invalidate language availability when needed."""
        keywords = parse_audio_keywords(latin_audio_keywords)
        if not keywords:
            keywords = parse_audio_keywords(DEFAULT_LATIN_AUDIO_KEYWORDS)
        if keywords != self.keywords or bool(hide_non_latin_items) != self.hide_non_matching:
            self._availability_cache.clear()
        self.prefer_h264 = bool(prefer_h264)
        self.prefer_smaller_size = bool(prefer_smaller_size)
        self.force_transcode = bool(force_transcode)
        self.keywords = keywords
        self.hide_non_matching = bool(hide_non_latin_items)

    async def get_streams(
        self,
        media_type: str,
        media_id: str,
        profile: str = PROFILE_DEFAULT,
    ) -> list[dict[str, Any]]:
        """Fetch streams and apply entry preferences and language filtering."""
        provider_profile = PROFILE_DEFAULT if profile == PROFILE_LATIN else profile
        streams = await self._original_get_streams(
            media_type,
            media_id,
            provider_profile,
        )
        enriched: list[dict[str, Any]] = []
        for stream in streams:
            item = dict(stream)
            item["_bridge_profile"] = profile
            item["_bridge_prefer_h264"] = self.prefer_h264
            item["_bridge_prefer_smaller_size"] = self.prefer_smaller_size
            item["_bridge_force_transcode"] = self.force_transcode
            enriched.append(item)
        if profile != PROFILE_LATIN:
            return enriched
        matched = [
            stream
            for stream in enriched
            if stream_has_spanish_audio(stream, self.keywords)
        ]
        if not matched and enriched:
            phrases = ", ".join(self.keywords[:12])
            raise SpanishAudioSourceNotFound(
                "No source from the main provider matched the configured "
                f"Spanish/Latin audio keywords ({phrases})"
            )
        return matched

    def catalogs(
        self,
        media_type: str | None = None,
        profile: str = PROFILE_DEFAULT,
    ) -> list[tuple[LoadedAddon, dict[str, Any]]]:
        """Return normal catalogs or filtered proxies for the Latin profile."""
        catalogs = self._original_catalogs(media_type, profile)
        if profile != PROFILE_LATIN or not self.hide_non_matching:
            return catalogs
        return [(self._catalog_addon(addon), catalog) for addon, catalog in catalogs]

    def get_addon(self, manifest_url: str) -> LoadedAddon:
        """Resolve both real add-ons and the synthetic filtered catalogs."""
        for addon in self._catalog_addons.values():
            if addon.client.manifest_url == manifest_url:
                return addon
        return self._original_get_addon(manifest_url)

    def _catalog_addon(self, addon: LoadedAddon) -> LoadedAddon:
        key = str(addon.client.manifest_url)
        if key not in self._catalog_addons:
            self._catalog_addons[key] = LoadedAddon(
                client=_FilteredCatalogClient(self, addon.client),
                manifest=addon.manifest,
                roles=addon.roles,
            )
        return self._catalog_addons[key]

    async def filter_catalog(
        self,
        metas: list[dict[str, Any]],
        media_type: str,
    ) -> list[dict[str, Any]]:
        """Remove confirmed non-matches while preserving uncertain provider errors."""
        if not self.hide_non_matching or not metas:
            return metas
        statuses = await asyncio.gather(
            *(self._safe_availability(media_type, meta) for meta in metas)
        )
        return [
            meta
            for meta, status in zip(metas, statuses, strict=True)
            if status is not False
        ]

    async def _safe_availability(
        self,
        media_type: str,
        meta: dict[str, Any],
    ) -> bool | None:
        try:
            return await self._availability(media_type, meta)
        except Exception:  # noqa: BLE001 - a catalog outage must not hide everything.
            _LOGGER.warning(
                "Unexpected Spanish-audio catalog probe failure for %s/%s",
                media_type,
                meta.get("id"),
                exc_info=True,
            )
            return None

    async def _availability(
        self,
        media_type: str,
        meta: dict[str, Any],
    ) -> bool | None:
        media_id = meta.get("id")
        if not isinstance(media_id, str) or not media_id:
            return None
        key = (media_type, media_id)
        now = asyncio.get_running_loop().time()
        cached = self._availability_cache.get(key)
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]
        if media_type == "series":
            result = await self._series_has_source(media_id)
        else:
            result = await self._video_has_source(media_type, media_id)
        if result is not None:
            self._availability_cache[key] = (now, result)
        return result

    def _semaphore(self) -> asyncio.Semaphore:
        if self._probe_semaphore is None:
            self._probe_semaphore = asyncio.Semaphore(_CATALOG_CONCURRENCY)
        return self._probe_semaphore

    async def _video_has_source(
        self,
        media_type: str,
        media_id: str,
    ) -> bool | None:
        try:
            async with self._semaphore():
                streams = await self.get_streams(media_type, media_id, PROFILE_LATIN)
        except SpanishAudioSourceNotFound:
            return False
        except StremioBridgeError:
            _LOGGER.debug(
                "Spanish-audio availability probe failed for %s/%s",
                media_type,
                media_id,
                exc_info=True,
            )
            return None
        return bool(streams)

    async def _series_has_source(self, series_id: str) -> bool | None:
        try:
            async with self._semaphore():
                meta = await self.manager.get_meta("series", series_id, PROFILE_DEFAULT)
        except StremioBridgeError:
            _LOGGER.debug(
                "Spanish-audio series metadata probe failed for %s",
                series_id,
                exc_info=True,
            )
            return None
        videos = meta.get("videos", [])
        video_ids = (
            [
                str(video.get("id"))
                for video in videos
                if isinstance(video, dict) and isinstance(video.get("id"), str)
            ]
            if isinstance(videos, list)
            else []
        )
        candidates = representative_ids(video_ids, _SERIES_SAMPLE_COUNT)
        if not candidates:
            candidates = [series_id]
        unknown = False
        for video_id in candidates:
            result = await self._video_has_source("series", video_id)
            if result is True:
                return True
            if result is None:
                unknown = True
        return None if unknown else False


def install_source_preferences(
    manager: Any,
    *,
    prefer_h264: bool = DEFAULT_PREFER_H264,
    prefer_smaller_size: bool = DEFAULT_PREFER_SMALLER_SIZE,
    latin_audio_keywords: object = DEFAULT_LATIN_AUDIO_KEYWORDS,
    hide_non_latin_items: bool = DEFAULT_HIDE_NON_LATIN_ITEMS,
    force_transcode: bool = False,
) -> SourcePreferences:
    """Install once, then configure the manager decorator for one entry."""
    preferences = getattr(manager, "_bridge_source_preferences", None)
    if not isinstance(preferences, SourcePreferences):
        preferences = SourcePreferences(manager)
        manager._bridge_source_preferences = preferences
        manager.get_streams = preferences.get_streams
        manager.catalogs = preferences.catalogs
        manager.get_addon = preferences.get_addon
    preferences.configure(
        prefer_h264=prefer_h264,
        prefer_smaller_size=prefer_smaller_size,
        latin_audio_keywords=latin_audio_keywords,
        hide_non_latin_items=hide_non_latin_items,
        force_transcode=force_transcode,
    )
    return preferences


def parse_audio_keywords(value: object) -> tuple[str, ...]:
    """Parse comma, semicolon or newline separated audio markers."""
    if isinstance(value, (list, tuple, set)):
        raw = "\n".join(str(item) for item in value)
    else:
        raw = str(value or "")
    for separator in (";", "\n"):
        raw = raw.replace(separator, ",")
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))


def stream_has_spanish_audio(
    stream: dict[str, Any],
    keywords: tuple[str, ...] | None = None,
) -> bool:
    """Return whether release metadata advertises configured Spanish/Latin audio."""
    hints = stream.get("behaviorHints")
    filename = hints.get("filename") if isinstance(hints, dict) else None
    raw_text = "\n".join(
        str(value)
        for value in (
            stream.get("name"),
            stream.get("title"),
            stream.get("description"),
            filename,
        )
        if value
    )
    normalized = normalize_text(raw_text)
    padded = f" {normalized} "
    markers = keywords or parse_audio_keywords(DEFAULT_LATIN_AUDIO_KEYWORDS)
    for marker in markers:
        normalized_marker = normalize_text(marker)
        if normalized_marker and f" {normalized_marker} " in padded:
            return True
        if not normalized_marker and marker and marker in raw_text:
            return True
    return False


def representative_ids(values: list[str], count: int) -> list[str]:
    """Sample the beginning, middle and end without probing an entire series."""
    unique = list(dict.fromkeys(values))
    if len(unique) <= count:
        return unique
    if count <= 1:
        return [unique[0]]
    if count == 2:
        return [unique[0], unique[-1]]
    if count == 3:
        return [unique[0], unique[len(unique) // 2], unique[-1]]
    indexes = [0, 1, len(unique) // 2, len(unique) - 2, len(unique) - 1]
    return [unique[index] for index in indexes[:count]]


def normalize_text(value: object) -> str:
    """Normalize release text for accent- and punctuation-insensitive matching."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = "".join(char if char.isalnum() else " " for char in text)
    return " ".join(text.split())
