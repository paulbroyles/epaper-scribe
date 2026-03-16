"""Config flow for E-Paper Scribe."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_API_KEY,
    CONF_CALENDAR_TYPE,
    CONF_DEFAULT_SIZE,
    CONF_MEDIA_PLAYER_ENTITY,
    CONF_PALETTE,
    CONF_PROVIDER_TYPE,
    DOMAIN,
    PALETTE_BWR,
    PROVIDER_NOW_PLAYING,
    PROVIDER_SAINTS_DAY,
    PROVIDER_WORD_OF_DAY,
)
from .providers.now_playing import NowPlayingProvider
from .providers.saints_day import SaintsDayProvider
from .providers.word_of_day import WordOfDayProvider

PROVIDER_REGISTRY = {
    PROVIDER_NOW_PLAYING: NowPlayingProvider,
    PROVIDER_SAINTS_DAY: SaintsDayProvider,
    PROVIDER_WORD_OF_DAY: WordOfDayProvider,
}

_PALETTE_OPTIONS = ["bw", "bwr", "bwry"]
_CALENDAR_OPTIONS = ["anglican", "catholic"]


class EpaperScribeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: menu → provider-specific form."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options={
                PROVIDER_NOW_PLAYING: "Now Playing",
                PROVIDER_SAINTS_DAY: "Liturgical Calendar",
                PROVIDER_WORD_OF_DAY: "Word of the Day",
            },
        )

    async def async_step_now_playing(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Now Playing",
                data={CONF_PROVIDER_TYPE: PROVIDER_NOW_PLAYING, **user_input},
            )
        return self.async_show_form(
            step_id="now_playing",
            data_schema=vol.Schema({
                vol.Required(CONF_MEDIA_PLAYER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(CONF_PALETTE, default=PALETTE_BWR): SelectSelector(
                    SelectSelectorConfig(
                        options=_PALETTE_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_DEFAULT_SIZE, default="128x128"): TextSelector(),
            }),
        )

    async def async_step_saints_day(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Liturgical Calendar",
                data={CONF_PROVIDER_TYPE: PROVIDER_SAINTS_DAY, **user_input},
            )
        return self.async_show_form(
            step_id="saints_day",
            data_schema=vol.Schema({
                vol.Optional(CONF_CALENDAR_TYPE, default="anglican"): SelectSelector(
                    SelectSelectorConfig(
                        options=_CALENDAR_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_PALETTE, default=PALETTE_BWR): SelectSelector(
                    SelectSelectorConfig(
                        options=_PALETTE_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_DEFAULT_SIZE, default="64x64"): TextSelector(),
            }),
        )

    async def async_step_word_of_day(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Word of the Day",
                data={CONF_PROVIDER_TYPE: PROVIDER_WORD_OF_DAY, **user_input},
            )
        return self.async_show_form(
            step_id="word_of_day",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_PALETTE, default=PALETTE_BWR): SelectSelector(
                    SelectSelectorConfig(
                        options=_PALETTE_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_DEFAULT_SIZE, default="296x128"): TextSelector(),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EpaperScribeOptionsFlow:
        return EpaperScribeOptionsFlow(config_entry)


class EpaperScribeOptionsFlow(config_entries.OptionsFlow):
    """Options flow for reconfiguring a provider without removing and re-adding."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        provider_type = self._config_entry.data.get(CONF_PROVIDER_TYPE)
        current = {**self._config_entry.data, **self._config_entry.options}

        if provider_type == PROVIDER_NOW_PLAYING:
            schema = vol.Schema({
                vol.Required(
                    CONF_MEDIA_PLAYER_ENTITY,
                    default=current.get(CONF_MEDIA_PLAYER_ENTITY, ""),
                ): EntitySelector(EntitySelectorConfig(domain="media_player")),
                vol.Optional(
                    CONF_PALETTE,
                    default=current.get(CONF_PALETTE, PALETTE_BWR),
                ): SelectSelector(SelectSelectorConfig(
                    options=_PALETTE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Optional(
                    CONF_DEFAULT_SIZE,
                    default=current.get(CONF_DEFAULT_SIZE, "128x128"),
                ): TextSelector(),
            })
        elif provider_type == PROVIDER_SAINTS_DAY:
            schema = vol.Schema({
                vol.Optional(
                    CONF_CALENDAR_TYPE,
                    default=current.get(CONF_CALENDAR_TYPE, "anglican"),
                ): SelectSelector(SelectSelectorConfig(
                    options=_CALENDAR_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Optional(
                    CONF_PALETTE,
                    default=current.get(CONF_PALETTE, PALETTE_BWR),
                ): SelectSelector(SelectSelectorConfig(
                    options=_PALETTE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Optional(
                    CONF_DEFAULT_SIZE,
                    default=current.get(CONF_DEFAULT_SIZE, "64x64"),
                ): TextSelector(),
            })
        elif provider_type == PROVIDER_WORD_OF_DAY:
            schema = vol.Schema({
                vol.Required(
                    CONF_API_KEY,
                    default=current.get(CONF_API_KEY, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_PALETTE,
                    default=current.get(CONF_PALETTE, PALETTE_BWR),
                ): SelectSelector(SelectSelectorConfig(
                    options=_PALETTE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Optional(
                    CONF_DEFAULT_SIZE,
                    default=current.get(CONF_DEFAULT_SIZE, "296x128"),
                ): TextSelector(),
            })
        else:
            return self.async_abort(reason="unknown_provider")

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=schema)
