"""Install the optional Stremio account layer without replacing playback code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .account_client import StremioAccountClient, account_url_id, addon_descriptor
from .api import StremioAddonClient, StremioBridgeError
from .const import (
    ACCOUNT_PROVIDER_ACCOUNT,
    ACCOUNT_PROVIDER_HYBRID,
    CONF_ACCOUNT_AUTH_KEY,
    CONF_ACCOUNT_EMAIL,
    CONF_ACCOUNT_ENABLED,
    CONF_ACCOUNT_PROVIDER_MODE,
    DEFAULT_ACCOUNT_ENABLED,
    DEFAULT_ACCOUNT_PROVIDER_MODE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_REGISTRY_KEY = "account_runtimes"
_PATCH_ATTR = "_bridge_account_coordinator_patched"


class AccountAddonClient(StremioAddonClient):
    """Stremio add-on client that avoids echoing private URLs in exceptions."""

    def __init__(self, session, manifest_url: str, safe_name: str) -> None:
        super().__init__(session, manifest_url)
        self.safe_name = safe_name

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            return await super()._get_json(url)
        except StremioBridgeError as err:
            raise type(err)(f"Account add-on {self.safe_name} request failed") from err


class StremioAccountCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Periodically refresh the linked Stremio account."""

    def __init__(self, hass: HomeAssistant, client: StremioAccountClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} account",
            update_interval=timedelta(minutes=5),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_snapshot()
        except StremioBridgeError as err:
            raise UpdateFailed(str(err)) from err


@dataclass
class StremioAccountRuntime:
    """Entry-scoped account state kept outside the slotted bridge runtime."""

    entry_id: str
    client: StremioAccountClient
    coordinator: StremioAccountCoordinator
    provider_mode: str
    private_urls: set[str]
    tracker: Any | None = None


def remove_account_runtime(hass: HomeAssistant, entry_id: str) -> None:
    """Forget one entry-scoped account runtime."""
    _registry(hass).pop(entry_id, None)


def get_account_runtime(
    hass: HomeAssistant, entry_id: str
) -> StremioAccountRuntime | None:
    registry = hass.data.get(DOMAIN, {}).get(_REGISTRY_KEY, {})
    runtime = registry.get(entry_id) if isinstance(registry, dict) else None
    return runtime if isinstance(runtime, StremioAccountRuntime) else None


async def async_install_account_bridge(
    hass: HomeAssistant,
    entry: ConfigEntry,
    bridge_runtime: Any,
) -> StremioAccountRuntime | None:
    """Load account data and optionally merge its add-ons into the manager."""
    current = {**entry.data, **entry.options}
    if not bool(current.get(CONF_ACCOUNT_ENABLED, DEFAULT_ACCOUNT_ENABLED)):
        _registry(hass).pop(entry.entry_id, None)
        return None
    email = str(current.get(CONF_ACCOUNT_EMAIL, "") or "").strip()
    auth_key = str(current.get(CONF_ACCOUNT_AUTH_KEY, "") or "").strip()
    if not email or not auth_key:
        _LOGGER.warning("Stremio account is enabled but no saved auth key is available")
        return None

    client = StremioAccountClient(
        async_get_clientsession(hass), email=email, auth_key=auth_key
    )
    coordinator = StremioAccountCoordinator(hass, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # noqa: BLE001 - account failure must not break playback.
        _LOGGER.warning("Could not load linked Stremio account: %s", err)
        return None
    provider_mode = str(
        current.get(CONF_ACCOUNT_PROVIDER_MODE, DEFAULT_ACCOUNT_PROVIDER_MODE)
    )
    private_urls = await install_account_providers(
        bridge_runtime.manager,
        async_get_clientsession(hass),
        client.raw_addons,
        provider_mode,
    )
    runtime = StremioAccountRuntime(
        entry_id=entry.entry_id,
        client=client,
        coordinator=coordinator,
        provider_mode=provider_mode,
        private_urls=private_urls,
    )
    _registry(hass)[entry.entry_id] = runtime
    install_account_coordinator_redaction(hass)
    return runtime


async def install_account_providers(
    manager: Any,
    session: Any,
    raw_addons: list[dict[str, Any]],
    provider_mode: str,
) -> set[str]:
    """Register account add-ons while preserving a working manual configuration."""
    if provider_mode not in {ACCOUNT_PROVIDER_ACCOUNT, ACCOUNT_PROVIDER_HYBRID}:
        return set()
    descriptors = [
        descriptor
        for addon in raw_addons
        if (descriptor := addon_descriptor(addon)) is not None
    ]
    if not descriptors:
        _LOGGER.warning(
            "Linked Stremio account returned no usable add-ons; keeping manual providers"
        )
        return set()

    previous_clients = dict(getattr(manager, "_clients", {}))
    previous_roles = {
        url: set(roles) for url, roles in getattr(manager, "_roles", {}).items()
    }
    private_urls: set[str] = set()
    try:
        if provider_mode == ACCOUNT_PROVIDER_ACCOUNT:
            _remove_manual_main_roles(manager)
        for descriptor in descriptors:
            raw_url = str(descriptor["transport_url"])
            safe_name = str(descriptor["name"])
            try:
                client = AccountAddonClient(session, raw_url, safe_name)
            except StremioBridgeError:
                continue
            normalized = client.manifest_url
            private_urls.add(normalized)
            manager._clients[normalized] = client
            manager._roles.setdefault(normalized, set()).update(descriptor["roles"])
        if not private_urls:
            raise StremioBridgeError("No account add-on URL could be loaded")
        await manager.async_refresh()
    except Exception as err:  # noqa: BLE001 - account providers are optional.
        manager._clients.clear()
        manager._clients.update(previous_clients)
        manager._roles.clear()
        manager._roles.update(previous_roles)
        try:
            await manager.async_refresh()
        except Exception:  # noqa: BLE001 - preserve the original bridge state best-effort.
            pass
        _LOGGER.warning("Could not activate Stremio account providers: %s", err)
        return set()
    return private_urls


def _remove_manual_main_roles(manager: Any) -> None:
    for url, roles in list(getattr(manager, "_roles", {}).items()):
        roles.difference_update({"catalog", "stream", "subtitle"})
        if roles:
            continue
        manager._roles.pop(url, None)
        manager._clients.pop(url, None)


def install_account_coordinator_redaction(hass: HomeAssistant) -> None:
    """Redact account add-on transport URLs from entity attributes and diagnostics."""
    from .coordinator import StremioBridgeCoordinator

    if getattr(StremioBridgeCoordinator, _PATCH_ATTR, False):
        return
    original = StremioBridgeCoordinator._async_update_data

    async def _async_update_data(self):
        data = await original(self)
        private_urls = _private_urls_for_manager(hass, self.manager)
        if not private_urls:
            return data
        addons = data.get("addons", [])
        if isinstance(addons, list):
            data["addons"] = [
                {
                    **addon,
                    "manifest_url": account_url_id(str(addon.get("manifest_url") or "")),
                    "source": "stremio_account",
                }
                if str(addon.get("manifest_url") or "") in private_urls
                else addon
                for addon in addons
                if isinstance(addon, dict)
            ]
        errors = data.get("addon_errors", {})
        if isinstance(errors, dict):
            data["addon_errors"] = {
                (
                    account_url_id(str(url))
                    if str(url) in private_urls
                    else str(url)
                ): error
                for url, error in errors.items()
            }
        return data

    StremioBridgeCoordinator._async_update_data = _async_update_data
    setattr(StremioBridgeCoordinator, _PATCH_ATTR, True)


def _private_urls_for_manager(hass: HomeAssistant, manager: Any) -> set[str]:
    for runtime in _registry(hass).values():
        bridge_entry = hass.config_entries.async_get_entry(runtime.entry_id)
        if bridge_entry is None:
            continue
        bridge_runtime = getattr(bridge_entry, "runtime_data", None)
        if bridge_runtime is not None and getattr(bridge_runtime, "manager", None) is manager:
            return set(runtime.private_urls)
    return set()


def _registry(hass: HomeAssistant) -> dict[str, StremioAccountRuntime]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    registry = domain_data.setdefault(_REGISTRY_KEY, {})
    return registry
