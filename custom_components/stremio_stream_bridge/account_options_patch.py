"""Add optional Stremio account fields to the established options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .account_client import StremioAccountClient
from .api import StremioBridgeError
from .const import (
    ACCOUNT_PROVIDER_MODES,
    CONF_ACCOUNT_AUTH_KEY,
    CONF_ACCOUNT_EMAIL,
    CONF_ACCOUNT_ENABLED,
    CONF_ACCOUNT_PASSWORD,
    CONF_ACCOUNT_PROVIDER_MODE,
    DEFAULT_ACCOUNT_ENABLED,
    DEFAULT_ACCOUNT_PROVIDER_MODE,
)

_PATCH_ATTR = "_bridge_account_options_patched"


def install_account_options_patch() -> None:
    """Append account controls and exchange passwords for an auth key on save."""
    from .config_flow import StremioStreamBridgeOptionsFlow

    if getattr(StremioStreamBridgeOptionsFlow, _PATCH_ATTR, False):
        return
    original = StremioStreamBridgeOptionsFlow.async_step_init

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        account_error = False
        prepared = None if user_input is None else dict(user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        if prepared is not None:
            enabled = bool(prepared.get(CONF_ACCOUNT_ENABLED, DEFAULT_ACCOUNT_ENABLED))
            password = str(prepared.pop(CONF_ACCOUNT_PASSWORD, "") or "")
            if enabled:
                email = str(prepared.get(CONF_ACCOUNT_EMAIL, "") or "").strip()
                auth_key = str(current.get(CONF_ACCOUNT_AUTH_KEY, "") or "").strip()
                client = StremioAccountClient(
                    async_get_clientsession(self.hass), email=email, auth_key=auth_key
                )
                try:
                    if password:
                        auth_key = await client.async_login(password)
                    else:
                        await client.async_get_user()
                    prepared[CONF_ACCOUNT_EMAIL] = email
                    prepared[CONF_ACCOUNT_AUTH_KEY] = auth_key
                except StremioBridgeError:
                    account_error = True
            else:
                prepared[CONF_ACCOUNT_EMAIL] = ""
                prepared[CONF_ACCOUNT_AUTH_KEY] = ""
                prepared[CONF_ACCOUNT_PROVIDER_MODE] = DEFAULT_ACCOUNT_PROVIDER_MODE

        result = await original(self, None if account_error else prepared)
        schema = result.get("data_schema") if isinstance(result, dict) else None
        if not isinstance(schema, vol.Schema):
            return result

        displayed = {**current, **(user_input or {})}
        fields = dict(schema.schema)
        fields.update(
            {
                vol.Required(
                    CONF_ACCOUNT_ENABLED,
                    default=displayed.get(
                        CONF_ACCOUNT_ENABLED, DEFAULT_ACCOUNT_ENABLED
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_ACCOUNT_EMAIL,
                    default=str(displayed.get(CONF_ACCOUNT_EMAIL, "") or ""),
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Optional(
                    CONF_ACCOUNT_PASSWORD,
                    default="",
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required(
                    CONF_ACCOUNT_PROVIDER_MODE,
                    default=str(
                        displayed.get(
                            CONF_ACCOUNT_PROVIDER_MODE,
                            DEFAULT_ACCOUNT_PROVIDER_MODE,
                        )
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(options=ACCOUNT_PROVIDER_MODES)
                ),
            }
        )
        result["data_schema"] = vol.Schema(fields)
        if account_error:
            result["errors"] = {"base": "account_auth_failed"}
        return result

    StremioStreamBridgeOptionsFlow.async_step_init = async_step_init
    setattr(StremioStreamBridgeOptionsFlow, _PATCH_ATTR, True)
