"""Public search and content-resolution helpers for voice and automation clients."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import logging
import re
from typing import Any, Protocol
import unicodedata

from .const import PROFILE_DEFAULT, PROFILE_LATIN, PROFILE_SPORTS

_LOGGER = logging.getLogger(__name__)
_YEAR_PATTERN = re.compile(r"(?<!\d)(?:18|19|20|21)\d{2}(?!\d)")
_PUBLIC_RESULT_KEYS = (
    "media_id",
    "media_type",
    "title",
    "year",
    "poster",
    "background",
    "description",
)


class SearchRuntime(Protocol):
    """Runtime shape needed by the public search service."""

    manager: Any
    last_search_query: str | None
    last_search_results: list[dict[str, Any]]


@dataclass(slots=True)
class RankedResult:
    """Internal ranking data that is never exposed through the service API."""

    result: dict[str, Any]
    original: dict[str, Any]
    index: int
    score: float
    title_ratio: float
    word_overlap: float
    exact_title: bool
    year_matches: bool


def normalize_title(value: object) -> str:
    """Normalize a spoken or provider title without external dependencies."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = "".join(char if char.isalnum() else " " for char in text)
    return " ".join(text.split())


def extract_year(value: object) -> int | None:
    """Extract a plausible year from numbers, release strings or metadata."""
    if isinstance(value, dict):
        for key in ("year", "releaseInfo", "released"):
            year = extract_year(value.get(key))
            if year is not None:
                return year
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2199 else None
    if isinstance(value, float) and value.is_integer():
        return extract_year(int(value))
    match = _YEAR_PATTERN.search(str(value or ""))
    return int(match.group(0)) if match else None


def normalize_public_result(
    meta: dict[str, Any], media_type: str | None = None
) -> dict[str, Any]:
    """Convert provider metadata into the stable public service contract."""
    resolved_type = (
        media_type
        or meta.get("_bridge_media_type")
        or meta.get("type")
        or None
    )
    title = meta.get("name") or meta.get("title") or ""
    result: dict[str, Any] = {
        "media_id": meta.get("id") or meta.get("media_id") or None,
        "media_type": str(resolved_type) if resolved_type else None,
        "title": str(title),
        "year": extract_year(meta),
        "poster": meta.get("poster") or None,
        "background": meta.get("background") or None,
        "description": meta.get("description") or meta.get("overview") or None,
    }
    return {key: result[key] for key in _PUBLIC_RESULT_KEYS}


def _usable_public_results(raw_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw in raw_results:
        public = normalize_public_result(raw)
        if public["media_id"] and public["media_type"] and public["title"]:
            results.append(public)
    return results


async def async_search_and_store(
    runtime: SearchRuntime,
    query: str,
    media_type: str = "all",
) -> dict[str, Any]:
    """Run a catalog search, preserve legacy runtime state and return public data."""
    clean_query = query.strip()
    media_types = ("movie", "series") if media_type == "all" else (media_type,)
    runtime.last_search_query = clean_query
    raw_results = await runtime.manager.search(clean_query, media_types)
    runtime.last_search_results = raw_results
    results = _usable_public_results(raw_results)
    return {
        "ok": True,
        "query": clean_query,
        "media_type": media_type,
        "count": len(results),
        "results": results,
    }


def rank_results(
    raw_results: list[dict[str, Any]],
    query: str,
    *,
    requested_year: int | None = None,
) -> list[RankedResult]:
    """Rank catalog results conservatively for a spoken-title resolver."""
    normalized_query = normalize_title(query)
    query_words = set(normalized_query.split())
    ranked: list[RankedResult] = []

    for index, raw in enumerate(raw_results):
        public = normalize_public_result(raw)
        if not public["media_id"] or not public["media_type"] or not public["title"]:
            continue
        normalized_candidate = normalize_title(public["title"])
        if not normalized_candidate:
            continue
        candidate_words = set(normalized_candidate.split())
        exact_title = normalized_candidate == normalized_query
        starts_query = normalized_candidate.startswith(normalized_query)
        ratio = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
        overlap = (
            len(query_words & candidate_words) / len(query_words)
            if query_words
            else 0.0
        )
        candidate_year = public["year"]
        year_matches = requested_year is None or candidate_year == requested_year

        score = ratio * 100.0 + overlap * 55.0
        if exact_title:
            score += 1000.0
        if starts_query and not exact_title:
            score += 120.0
        if requested_year is not None:
            score += 240.0 if candidate_year == requested_year else -240.0
        score -= index * 0.001

        ranked.append(
            RankedResult(
                result=public,
                original=raw,
                index=index,
                score=score,
                title_ratio=ratio,
                word_overlap=overlap,
                exact_title=exact_title,
                year_matches=year_matches,
            )
        )

    return sorted(ranked, key=lambda item: (-item.score, item.index))


def select_ranked_result(
    ranked: list[RankedResult],
    *,
    requested_year: int | None = None,
) -> tuple[str, RankedResult | None]:
    """Return exact, ambiguous or not_found without silently guessing."""
    if not ranked:
        return "not_found", None

    exact = [
        item
        for item in ranked
        if item.exact_title
        and (requested_year is None or item.result["year"] == requested_year)
    ]
    if len(exact) == 1:
        return "exact", exact[0]
    if len(exact) > 1:
        return "ambiguous", None

    top = ranked[0]
    if top.title_ratio < 0.45 and top.word_overlap == 0:
        return "not_found", None

    second = ranked[1] if len(ranked) > 1 else None
    score_gap = top.score - second.score if second else top.score
    # A fuzzy result is accepted only with a very close title and a clear lead.
    if (
        top.title_ratio >= 0.92
        and top.word_overlap >= 0.8
        and score_gap >= 35.0
        and top.year_matches
    ):
        return "exact", top
    return "ambiguous", None


def response_base(
    query: str,
    profile: str,
    media_type: str,
    year: int | None,
    season: int | None,
    episode: int | None,
) -> dict[str, Any]:
    """Build the stable response envelope shared by resolver outcomes."""
    return {
        "ok": True,
        "status": "not_found",
        "query": query,
        "profile": profile,
        "requested": {
            "media_type": media_type,
            "year": year,
            "season": season,
            "episode": episode,
        },
        "selected": None,
        "results": [],
    }


def error_response(
    *,
    query: str,
    profile: str,
    media_type: str,
    year: int | None,
    season: int | None,
    episode: int | None,
    message: str,
) -> dict[str, Any]:
    """Return a structured, non-sensitive resolver error for service clients."""
    return {
        **response_base(query, profile, media_type, year, season, episode),
        "ok": False,
        "status": "error",
        "error": message,
    }


def _safe_int(value: object, *, minimum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= minimum else None


def _episode_records(meta: dict[str, Any]) -> list[dict[str, Any]]:
    videos = meta.get("videos", [])
    if not isinstance(videos, list):
        return []
    episodes: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for video in videos:
        if not isinstance(video, dict):
            continue
        media_id = video.get("id")
        season = _safe_int(video.get("season"), minimum=0)
        episode = _safe_int(video.get("episode"), minimum=1)
        if not isinstance(media_id, str) or season is None or episode is None:
            continue
        key = (season, episode, media_id)
        if key in seen:
            continue
        seen.add(key)
        episodes.append(
            {
                "media_id": media_id,
                "season": season,
                "episode": episode,
                "title": str(
                    video.get("title")
                    or video.get("name")
                    or f"Episode {episode}"
                ),
                "thumbnail": video.get("thumbnail") or None,
                "released": video.get("released") or None,
                "description": video.get("description") or None,
            }
        )
    return sorted(episodes, key=lambda item: (item["season"], item["episode"]))


def _merge_public(base: dict[str, Any], detailed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    detail_public = normalize_public_result(detailed, str(base.get("media_type") or ""))
    for key, value in detail_public.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


async def _resolve_series(
    manager: Any,
    base: dict[str, Any],
    selected: RankedResult,
    *,
    profile: str,
    season: int | None,
    episode: int | None,
) -> dict[str, Any]:
    series_id = str(selected.result["media_id"])
    metadata_profile = PROFILE_LATIN if profile == PROFILE_LATIN else PROFILE_DEFAULT
    try:
        meta = await manager.get_meta("series", series_id, metadata_profile)
    except Exception:  # noqa: BLE001 - provider details remain in logs only.
        _LOGGER.exception("Could not resolve series metadata for %s", series_id)
        return {
            **base,
            "ok": False,
            "status": "error",
            "error": "Series metadata provider error",
        }

    series_public = _merge_public(selected.result, meta)
    episodes = _episode_records(meta)
    available_seasons = sorted({item["season"] for item in episodes})
    series_public["available_seasons"] = available_seasons

    if season is None or episode is None:
        response = {
            **base,
            "status": "series_needs_episode",
            "selected": series_public,
            "available_seasons": available_seasons,
        }
        if season is not None:
            available = [item for item in episodes if item["season"] == season]
            response["requested_season"] = season
            response["available_episodes"] = [
                {
                    "season": item["season"],
                    "episode": item["episode"],
                    "title": item["title"],
                }
                for item in available[:50]
            ]
        return response

    season_episodes = [item for item in episodes if item["season"] == season]
    matched = next(
        (item for item in season_episodes if item["episode"] == episode),
        None,
    )
    if matched is None:
        response = {
            **base,
            "status": "episode_not_found",
            "available_seasons": available_seasons,
        }
        if season_episodes:
            response["available_episodes"] = [
                {
                    "season": item["season"],
                    "episode": item["episode"],
                    "title": item["title"],
                }
                for item in season_episodes[:50]
            ]
        return response

    episode_selected = {
        "media_id": matched["media_id"],
        "media_type": "series",
        "series_id": series_id,
        "series_title": series_public["title"],
        "title": matched["title"],
        "year": extract_year(matched["released"]),
        "season": season,
        "episode": episode,
        "poster": matched["thumbnail"] or series_public.get("poster"),
        "background": series_public.get("background"),
        "description": matched["description"] or series_public.get("description"),
    }
    return {**base, "status": "exact", "selected": episode_selected}


async def async_resolve_content(
    manager: Any,
    *,
    query: str,
    media_type: str = "all",
    profile: str = PROFILE_DEFAULT,
    year: int | None = None,
    season: int | None = None,
    episode: int | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Resolve a spoken title into a movie, series or concrete episode."""
    clean_query = query.strip()
    limit = max(1, min(int(limit), 10))
    base = response_base(clean_query, profile, media_type, year, season, episode)

    if profile == PROFILE_SPORTS:
        return {
            **base,
            "ok": False,
            "status": "unsupported",
            "error": "Sports profile search is not supported yet",
        }

    media_types = ("movie", "series") if media_type == "all" else (media_type,)
    try:
        raw_results = await manager.search(clean_query, media_types)
    except Exception:  # noqa: BLE001 - do not expose provider URLs or secrets.
        _LOGGER.exception("Catalog search failed while resolving %r", clean_query)
        return {
            **base,
            "ok": False,
            "status": "error",
            "error": "Catalog provider error",
        }

    ranked = rank_results(raw_results, clean_query, requested_year=year)
    status, selected = select_ranked_result(ranked, requested_year=year)
    public_ranked = [item.result for item in ranked[:limit]]

    if status == "not_found":
        return {**base, "status": "not_found"}
    if status == "ambiguous" or selected is None:
        return {**base, "status": "ambiguous", "results": public_ranked}

    if selected.result["media_type"] == "series":
        return await _resolve_series(
            manager,
            base,
            selected,
            profile=profile,
            season=season,
            episode=episode,
        )

    chosen = selected.result
    try:
        detailed = await manager.get_meta("movie", str(chosen["media_id"]), PROFILE_DEFAULT)
    except Exception:  # noqa: BLE001 - search result is still a valid exact match.
        _LOGGER.debug("Movie metadata enrichment failed for %s", chosen["media_id"])
    else:
        chosen = _merge_public(chosen, detailed)
    return {**base, "status": "exact", "selected": chosen}
