"""Config flow for E-Paper Scribe."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_PROVIDER_TYPE,
    DOMAIN,
    PROVIDER_NOW_PLAYING,
    PROVIDER_SAINTS_DAY,
)
from .providers.now_playing import NowPlayingProvider
from .providers.saints_day import SaintsDayProvider

PROVIDER_REGISTRY = {
    PROVIDER_NOW_PLAYING: NowPlayingProvider,
    PROVIDER_SAINTS_DAY: SaintsDayProvider,
}

PROVIDER_LABELS = {
    PROVIDER_NOW_PLAYING: "Now Playing",
    PROVIDER_SAINTS_DAY: "Liturgical Calendar",
}


class EpaperScribeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: select provider type → provider-specific config."""

    VERSION = 1

    def __init__(self) -> None:
        self._provider_type: str | None = None

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: select provider type."""
        if user_input is not None:
            self._provider_type = user_input[CONF_PROVIDER_TYPE]
            return await self.async_step_provider()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_PROVIDER_TYPE): vol.In(PROVIDER_LABELS)}
            ),
        )

    async def async_step_provider(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: provider-specific configuration."""
        provider_class = PROVIDER_REGISTRY[self._provider_type]
        # ALLOW_EXTRA so HA doesn't reject provider_type if it carries over
        # from step 1 during form validation.
        schema = vol.Schema(provider_class.get_config_schema(), extra=vol.ALLOW_EXTRA)

        if user_input is not None:
            # Strip any keys not belonging to this provider before storing.
            provider_keys = {
                k.schema if hasattr(k, "schema") else k
                for k in provider_class.get_config_schema()
            }
            provider_input = {k: v for k, v in user_input.items() if k in provider_keys}
            data = {CONF_PROVIDER_TYPE: self._provider_type, **provider_input}
            return self.async_create_entry(
                title=PROVIDER_LABELS[self._provider_type], data=data
            )

        return self.async_show_form(step_id="provider", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EpaperScribeOptionsFlow:
        return EpaperScribeOptionsFlow(config_entry)


class EpaperScribeOptionsFlow(config_entries.OptionsFlow):
    """Options flow for reconfiguring a provider without removing and re-adding it."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        provider_type = self._config_entry.data.get(CONF_PROVIDER_TYPE)
        provider_class = PROVIDER_REGISTRY.get(provider_type)
        if provider_class is None:
            return self.async_abort(reason="unknown_provider")

        raw_schema = provider_class.get_config_schema()
        current = {**self._config_entry.data, **self._config_entry.options}

        # Rebuild schema with current values as defaults
        filled: dict = {}
        for key, validator in raw_schema.items():
            key_str = key.schema if hasattr(key, "schema") else str(key)
            default = current.get(key_str)
            if default is not None:
                filled[vol.Optional(key_str, default=default)] = validator
            else:
                filled[key] = validator

        schema = vol.Schema(filled, extra=vol.ALLOW_EXTRA)

        if user_input is not None:
            provider_keys = {
                k.schema if hasattr(k, "schema") else k
                for k in raw_schema
            }
            provider_input = {k: v for k, v in user_input.items() if k in provider_keys}
            return self.async_create_entry(title="", data=provider_input)

        return self.async_show_form(step_id="init", data_schema=schema)
