"""Aggregate Stremio add-ons by the resources declared in their manifests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any
import unicodedata

from .api import StremioAddonClient, StremioBridgeError, StremioProtocolError
from .const import PROFILE_DEFAULT, PROFILE_LATIN, PROFILE_SPORTS

_LOGGER = logging.getLogger(__name__)
_MAX_SEARCH_RESULTS = 50
_LATIN_AUDIO_PHRASES = (
    "audio latino",
    "espanol latino",
    "spanish latino",
    "dual latino",
    "latino",
    "latina",
    "latam",
    "latinoamerica",
    "latin america",
)
_LATIN_AUDIO_FLAGS = ("🇦🇷", "🇧🇴", "🇨🇱", "🇨🇴", "🇨🇷", "🇪🇨", "🇲🇽", "🇵🇪", "🇺🇾", "🇻🇪")


@dataclass(slots=True)
class LoadedAddon:
    """A validated add-on client and its current manifest."""

    client: StremioAddonClient
    manifest: dict[str, Any]
    roles: frozenset[str]

    @property
    def id(self) -> str:
        return str(self.manifest.get("id") or self.client.manifest_url)

    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or self.id)


class StremioAddonManager:
    """Route catalog, metadata, stream and subtitle requests across add-ons."""

    def __init__(
        self,
        catalog_clients: list[StremioAddonClient],
        stream_clients: list[StremioAddonClient],
        subtitle_clients: list[StremioAddonClient] | None = None,
        latin_clients: list[StremioAddonClient] | None = None,
        sports_clients: list[StremioAddonClient] | None = None,
    ) -> None:
        roles_by_url: dict[str, set[str]] = {}
        clients_by_url: dict[str, StremioAddonClient] = {}
        # Latin Audio intentionally reuses the main stream providers. The
        # latin_clients argument remains accepted so old config entries load,
        # but those legacy clients are not registered or contacted.
        if latin_clients:
            _LOGGER.info(
                "Ignoring %d legacy Latin Audio provider(s); the profile now filters "
                "the main stream providers by release-name keywords",
                len(latin_clients),
            )
        for role, clients in (
            ("catalog", catalog_clients),
            ("stream", stream_clients),
            ("subtitle", subtitle_clients or []),
            (PROFILE_SPORTS, sports_clients or []),
        ):
            for client in clients:
                clients_by_url[client.manifest_url] = client
                roles_by_url.setdefault(client.manifest_url, set()).add(role)
        self._clients = clients_by_url
        self._roles = roles_by_url
        self.addons: list[LoadedAddon] = []
        self.errors: dict[str, str] = {}
        self.last_subtitle_errors: dict[str, str] = {}

    async def async_refresh(self) -> list[LoadedAddon]:
        """Refresh every manifest, retaining all successfully loaded add-ons."""
        clients = list(self._clients.values())
        results = await asyncio.gather(
            *(client.get_manifest() for client in clients), return_exceptions=True
        )
        addons: list[LoadedAddon] = []
        errors: dict[str, str] = {}
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, BaseException):
                errors[client.manifest_url] = str(result)
                continue
            addons.append(
                LoadedAddon(
                    client=client,
                    manifest=result,
                    roles=frozenset(self._roles.get(client.manifest_url, set())),
                )
            )
        if not addons:
            detail = "; ".join(errors.values()) or "No add-on manifests were loaded"
            raise StremioProtocolError(detail)
        self.addons = addons
        self.errors = errors
        return addons

    def has_profile(self, profile: str) -> bool:
        """Return whether a playback profile is available."""
        if profile == PROFILE_DEFAULT:
            return True
        if profile == PROFILE_LATIN:
            return any("stream" in addon.roles for addon in self.addons)
        return any(profile in addon.roles for addon in self.addons)

    def catalogs(
        self,
        media_type: str | None = None,
        profile: str = PROFILE_DEFAULT,
    ) -> list[tuple[LoadedAddon, dict[str, Any]]]:
        """Return catalog declarations for one playback profile."""
        role = "catalog" if profile in {PROFILE_DEFAULT, PROFILE_LATIN} else profile
        return self._catalogs_for_role(role, media_type)

    def _catalogs_for_role(
        self, role: str, media_type: str | None
    ) -> list[tuple[LoadedAddon, dict[str, Any]]]:
        result: list[tuple[LoadedAddon, dict[str, Any]]] = []
        seen: set[tuple[str, str, str]] = set()
        for addon in self.addons:
            if role not in addon.roles:
                continue
            catalogs = addon.manifest.get("catalogs", [])
            if not isinstance(catalogs, list):
                continue
            for catalog in catalogs:
                if not isinstance(catalog, dict):
                    continue
                catalog_type = catalog.get("type")
                catalog_id = catalog.get("id")
                if not isinstance(catalog_type, str) or not isinstance(catalog_id, str):
                    continue
                if media_type and catalog_type != media_type:
                    continue
                key = (addon.client.manifest_url, catalog_type, catalog_id)
                if key in seen:
                    continue
                seen.add(key)
                result.append((addon, catalog))
        return result

    def get_addon(self, manifest_url: str) -> LoadedAddon:
        """Return a loaded add-on by manifest URL."""
        for addon in self.addons:
            if addon.client.manifest_url == manifest_url:
                return addon
        raise StremioProtocolError(f"Add-on is not loaded: {manifest_url}")

    async def get_catalog(
        self,
        manifest_url: str,
        media_type: str,
        catalog_id: str,
        extra: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch one catalog from its declaring add-on."""
        addon = self.get_addon(manifest_url)
        return await addon.client.get_catalog(media_type, catalog_id, extra)

    async def get_meta(
        self,
        media_type: str,
        media_id: str,
        profile: str = PROFILE_DEFAULT,
    ) -> dict[str, Any]:
        """Return metadata from the first compatible provider that succeeds."""
        preferred_role = (
            "catalog" if profile in {PROFILE_DEFAULT, PROFILE_LATIN} else profile
        )
        providers = [addon for addon in self.addons if preferred_role in addon.roles]
        if profile not in {PROFILE_DEFAULT, PROFILE_LATIN}:
            providers.extend(
                addon
                for addon in self.addons
                if "catalog" in addon.roles and addon not in providers
            )
        errors: list[str] = []
        for addon in providers:
            if not supports_resource(addon.manifest, "meta", media_type, media_id):
                continue
            try:
                return await addon.client.get_meta(media_type, media_id)
            except StremioBridgeError as err:
                errors.append(f"{addon.name}: {err}")
        detail = "; ".join(errors) or "No compatible metadata provider"
        raise StremioProtocolError(detail)

    async def get_streams(
        self,
        media_type: str,
        media_id: str,
        profile: str = PROFILE_DEFAULT,
    ) -> list[dict[str, Any]]:
        """Fetch and merge streams from compatible providers in one profile."""
        role = "stream" if profile in {PROFILE_DEFAULT, PROFILE_LATIN} else profile
        providers = [
            addon
            for addon in self.addons
            if role in addon.roles
            and supports_resource(addon.manifest, "stream", media_type, media_id)
        ]
        if not providers:
            raise StremioProtocolError(f"No compatible {profile} stream provider")
        results = await asyncio.gather(
            *(addon.client.get_streams(media_type, media_id) for addon in providers),
            return_exceptions=True,
        )
        merged: list[dict[str, Any]] = []
        errors: list[str] = []
        seen: set[str] = set()
        for addon, result in zip(providers, results, strict=True):
            if isinstance(result, BaseException):
                errors.append(f"{addon.name}: {result}")
                continue
            for provider_index, stream in enumerate(result):
                enriched = dict(stream)
                enriched["_bridge_addon_name"] = addon.name
                enriched["_bridge_addon_url"] = addon.client.manifest_url
                enriched["_bridge_provider_index"] = provider_index
                enriched["_bridge_profile"] = profile
                key = stream_key(enriched)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(enriched)
        if not merged and errors:
            raise StremioProtocolError("; ".join(errors))
        if profile == PROFILE_LATIN:
            latin_streams = [stream for stream in merged if stream_has_latin_audio(stream)]
            if not latin_streams and merged:
                phrases = ", ".join(_LATIN_AUDIO_PHRASES)
                raise StremioProtocolError(
                    "No source from the main provider matched Latin Audio keywords "
                    f"({phrases})"
                )
            return latin_streams
        return merged

    async def get_subtitles(
        self,
        media_type: str,
        media_id: str,
        extra: dict[str, str] | None = None,
        stream: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch and merge subtitle tracks from streams and subtitle providers."""
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        if stream is not None:
            embedded = stream.get("subtitles", [])
            if isinstance(embedded, list):
                for subtitle in embedded:
                    if isinstance(subtitle, dict):
                        _append_subtitle(merged, seen, subtitle, "Stream")

        providers = [
            addon
            for addon in self.addons
            if "subtitle" in addon.roles
            and supports_resource(addon.manifest, "subtitles", media_type, media_id)
        ]
        if not providers:
            self.last_subtitle_errors = {}
            return merged

        results = await asyncio.gather(
            *(addon.client.get_subtitles(media_type, media_id, extra) for addon in providers),
            return_exceptions=True,
        )
        errors: dict[str, str] = {}
        for addon, result in zip(providers, results, strict=True):
            if isinstance(result, BaseException):
                errors[addon.name] = str(result)
                _LOGGER.warning(
                    "Subtitle provider %s failed for %s/%s: %s",
                    addon.name,
                    media_type,
                    media_id,
                    result,
                )
                continue
            for subtitle in result:
                _append_subtitle(merged, seen, subtitle, addon.name)
        self.last_subtitle_errors = errors
        return merged

    async def search(
        self, query: str, media_types: tuple[str, ...] = ("movie", "series")
    ) -> list[dict[str, Any]]:
        """Search every default catalog that advertises the Stremio `search` extra."""
        clean_query = query.strip()
        if not clean_query:
            return []

        requests: list[tuple[LoadedAddon, dict[str, Any]]] = []
        seen_requests: set[tuple[str, str, str]] = set()
        for media_type in dict.fromkeys(media_types):
            for addon, catalog in self.catalogs(media_type, PROFILE_DEFAULT):
                if not catalog_supports_extra(catalog, "search"):
                    continue
                key = (
                    addon.client.manifest_url,
                    str(catalog.get("type") or ""),
                    str(catalog.get("id") or ""),
                )
                if key in seen_requests:
                    continue
                seen_requests.add(key)
                requests.append((addon, catalog))

        results = await asyncio.gather(
            *(
                addon.client.get_catalog(
                    str(catalog["type"]),
                    str(catalog["id"]),
                    {"search": clean_query},
                )
                for addon, catalog in requests
            ),
            return_exceptions=True,
        )
        metas: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for (addon, catalog), result in zip(requests, results, strict=True):
            if isinstance(result, BaseException):
                continue
            media_type = str(catalog["type"])
            for meta in result:
                media_id = meta.get("id")
                if not isinstance(media_id, str):
                    continue
                key = (media_type, media_id)
                if key in seen:
                    continue
                seen.add(key)
                enriched = dict(meta)
                enriched["_bridge_media_type"] = media_type
                enriched["_bridge_catalog_addon"] = addon.name
                metas.append(enriched)

        query_key = _normalize_search_text(clean_query)
        ranked = sorted(
            enumerate(metas),
            key=lambda item: (*_search_result_rank(item[1], query_key), item[0]),
        )
        return [meta for _, meta in ranked[:_MAX_SEARCH_RESULTS]]


def stream_has_latin_audio(stream: dict[str, Any]) -> bool:
    """Return whether release metadata advertises Latin American Spanish audio."""
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
    if any(flag in raw_text for flag in _LATIN_AUDIO_FLAGS):
        return True
    normalized = _normalize_search_text(raw_text)
    padded = f" {normalized} "
    return any(f" {phrase} " in padded for phrase in _LATIN_AUDIO_PHRASES)


def _normalize_search_text(value: object) -> str:
    """Normalize user, catalog and release text for stable matching."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = "".join(char if char.isalnum() else " " for char in text)
    return " ".join(text.split())


def _search_result_rank(meta: dict[str, Any], query: str) -> tuple[int, int]:
    """Put exact, prefix and substring title matches before provider order."""
    title = _normalize_search_text(meta.get("name") or meta.get("title"))
    comparable_title = _without_leading_article(title)
    if title == query or comparable_title == query:
        bucket = 0
    elif title.startswith(query) or comparable_title.startswith(query):
        bucket = 1
    elif query and query in title:
        bucket = 2
    else:
        bucket = 3
    return bucket, abs(len(comparable_title) - len(query))


def _without_leading_article(value: str) -> str:
    """Ignore common leading articles when ordering title search results."""
    words = value.split()
    if words and words[0] in {"a", "an", "the", "el", "la", "los", "las", "un", "una"}:
        return " ".join(words[1:])
    return value


def _append_subtitle(
    result: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    subtitle: dict[str, Any],
    provider: str,
) -> None:
    url = subtitle.get("url")
    lang = subtitle.get("lang")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return
    if not isinstance(lang, str) or not lang:
        lang = "und"
    key = (url, lang.lower())
    if key in seen:
        return
    seen.add(key)
    enriched = dict(subtitle)
    enriched["lang"] = lang.lower()
    enriched["_bridge_addon_name"] = provider
    result.append(enriched)


def manifest_has_resource(manifest: dict[str, Any], resource_name: str) -> bool:
    """Return whether a manifest declares a resource name."""
    resources = manifest.get("resources", [])
    if not isinstance(resources, list):
        return False
    return any(
        resource == resource_name
        or (isinstance(resource, dict) and resource.get("name") == resource_name)
        for resource in resources
    )


def supports_resource(
    manifest: dict[str, Any], resource_name: str, media_type: str, media_id: str
) -> bool:
    """Return whether a manifest advertises a resource for this content."""
    resources = manifest.get("resources", [])
    if not isinstance(resources, list):
        return False
    matched: dict[str, Any] | None = None
    for resource in resources:
        if resource == resource_name:
            matched = {}
            break
        if isinstance(resource, dict) and resource.get("name") == resource_name:
            matched = resource
            break
    if matched is None:
        return False
    types = matched.get("types") or manifest.get("types")
    if isinstance(types, list) and types and media_type not in types:
        return False
    prefixes = matched.get("idPrefixes") or manifest.get("idPrefixes")
    if isinstance(prefixes, list) and prefixes:
        return any(
            isinstance(prefix, str) and media_id.startswith(prefix)
            for prefix in prefixes
        )
    return True


def catalog_extra(catalog: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return a normalized catalog extra declaration."""
    extras = catalog.get("extra", [])
    if isinstance(extras, list):
        for extra in extras:
            if extra == name:
                return {"name": name}
            if isinstance(extra, dict) and extra.get("name") == name:
                return extra
    supported = catalog.get("extraSupported", [])
    if isinstance(supported, list) and name in supported:
        return {"name": name}
    return None


def catalog_supports_extra(catalog: dict[str, Any], name: str) -> bool:
    return catalog_extra(catalog, name) is not None


def catalog_required_extras(catalog: dict[str, Any]) -> list[str]:
    """Return required extra names from both current manifest formats."""
    result: list[str] = []
    raw_required = catalog.get("extraRequired", [])
    if isinstance(raw_required, list):
        result.extend(
            str(value) for value in raw_required if isinstance(value, str)
        )
    extras = catalog.get("extra", [])
    if isinstance(extras, list):
        for extra in extras:
            if isinstance(extra, dict) and extra.get("isRequired") and isinstance(
                extra.get("name"), str
            ):
                result.append(extra["name"])
    return list(dict.fromkeys(result))


def stream_key(stream: dict[str, Any]) -> str:
    """Build a stable-enough key for a stream across repeated provider queries."""
    info_hash = stream.get("infoHash")
    if isinstance(info_hash, str) and info_hash:
        return f"bt:{info_hash.lower()}:{stream.get('fileIdx', -1)}"
    for field in ("url", "externalUrl", "ytId"):
        value = stream.get(field)
        if isinstance(value, str) and value:
            return f"{field}:{value}"
    return "text:" + "|".join(
        str(stream.get(field) or "")
        for field in ("name", "title", "description")
    )
