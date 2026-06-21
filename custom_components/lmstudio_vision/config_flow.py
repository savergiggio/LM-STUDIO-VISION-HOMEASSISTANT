"""Config and options flow for LM Studio Vision."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LMStudioClient, LMStudioConnectionError
from .const import (
    CONF_API_KEY,
    CONF_AUTO_LOAD,
    CONF_CONTEXT_LENGTH,
    CONF_HOST,
    CONF_HTTPS,
    CONF_MODEL,
    CONF_PORT,
    CONF_TIMEOUT,
    DEFAULT_AUTO_LOAD,
    DEFAULT_HOST,
    DEFAULT_HTTPS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _validate(hass, data: dict[str, Any]) -> list[str]:
    """Try to reach the server and return the available model list."""
    session = async_get_clientsession(hass)
    client = LMStudioClient(
        session,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        use_https=data.get(CONF_HTTPS, False),
        api_key=data.get(CONF_API_KEY),
        timeout=data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )
    return await client.async_list_models()


class LMStudioVisionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: collect connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()
            try:
                models = await _validate(self.hass, user_input)
            except LMStudioConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating LM Studio")
                errors["base"] = "unknown"
            else:
                title = f"LM Studio ({user_input[CONF_HOST]}:{user_input[CONF_PORT]})"
                # Default the model to the first loaded one, if any.
                if models and not user_input.get(CONF_MODEL):
                    user_input[CONF_MODEL] = models[0]
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_HTTPS, default=DEFAULT_HTTPS): bool,
                vol.Optional(CONF_API_KEY, default=""): str,
                vol.Optional(CONF_MODEL, default=""): str,
                vol.Optional(CONF_AUTO_LOAD, default=DEFAULT_AUTO_LOAD): bool,
                vol.Optional(CONF_CONTEXT_LENGTH, default=0): int,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LMStudioVisionOptionsFlow(entry)


class LMStudioVisionOptionsFlow(OptionsFlow):
    """Allow changing model/timeout after setup."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the entry."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._entry.data, **self._entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODEL, default=current.get(CONF_MODEL, "")
                ): str,
                vol.Optional(
                    CONF_AUTO_LOAD,
                    default=current.get(CONF_AUTO_LOAD, DEFAULT_AUTO_LOAD),
                ): bool,
                vol.Optional(
                    CONF_CONTEXT_LENGTH,
                    default=current.get(CONF_CONTEXT_LENGTH, 0) or 0,
                ): int,
                vol.Optional(
                    CONF_TIMEOUT,
                    default=current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                ): int,
                vol.Optional(
                    CONF_API_KEY, default=current.get(CONF_API_KEY, "")
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
