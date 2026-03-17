"""E-Paper Scribe — content provider integration for e-ink displays.

Architecture: content provider, not display controller.

This integration exposes services that generate dithered images and metadata
on demand. Display layout logic lives entirely in user automations/blueprints.

Each config entry = one provider instance. Multiple entries supported.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import (
    CONF_PROVIDER_TYPE,
    DOMAIN,
    PROVIDER_NOW_PLAYING,
    PROVIDER_SAINTS_DAY,
    PROVIDER_TODAY_IN_HISTORY,
    PROVIDER_WORD_OF_DAY,
)
from .providers.now_playing import NowPlayingProvider
from .providers.saints_day import SaintsDayProvider
from .providers.today_in_history import TodayInHistoryProvider
from .providers.word_of_day import WordOfDayProvider

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["image", "sensor"]

PROVIDER_REGISTRY = {
    PROVIDER_NOW_PLAYING: NowPlayingProvider,
    PROVIDER_SAINTS_DAY: SaintsDayProvider,
    PROVIDER_WORD_OF_DAY: WordOfDayProvider,
    PROVIDER_TODAY_IN_HISTORY: TodayInHistoryProvider,
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register services at domain load, before any config entries exist."""
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a provider config entry."""
    hass.data.setdefault(DOMAIN, {})

    provider_type = entry.data.get(CONF_PROVIDER_TYPE)
    provider_class = PROVIDER_REGISTRY.get(provider_type)
    if provider_class is None:
        _LOGGER.error("Unknown provider type: %s", provider_type)
        return False

    config = {**entry.data, **entry.options}
    provider = provider_class(hass, config)
    try:
        await provider.async_initialize()
    except Exception as exc:
        _LOGGER.error("Provider initialization failed for %s: %s", provider_type, exc)

    hass.data[DOMAIN][entry.entry_id] = {
        "provider": provider,
        "entities": [],
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services. Safe to call multiple times — only registers once."""
    if hass.services.has_service(DOMAIN, "render_now_playing"):
        return

    async def handle_render_now_playing(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data.get("entry_id")
        kwargs = {k: v for k, v in call.data.items() if k != "entry_id"}

        for eid, entry_data in hass.data[DOMAIN].items():
            if not isinstance(entry_data["provider"], NowPlayingProvider):
                continue
            if entry_id is not None and eid != entry_id:
                continue
            result = await entry_data["provider"].async_render(**kwargs)
            _push_entity_updates(entry_data["entities"])
            return result

        _LOGGER.warning("render_now_playing: no matching Now Playing entry found")
        return {}

    async def handle_render_saints_day(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data.get("entry_id")
        kwargs = {k: v for k, v in call.data.items() if k != "entry_id"}

        for eid, entry_data in hass.data[DOMAIN].items():
            if not isinstance(entry_data["provider"], SaintsDayProvider):
                continue
            if entry_id is not None and eid != entry_id:
                continue
            result = await entry_data["provider"].async_render(**kwargs)
            _push_entity_updates(entry_data["entities"])
            return result

        _LOGGER.warning("render_saints_day: no matching Liturgical Calendar entry found")
        return {}

    async def handle_render_word_of_day(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data.get("entry_id")
        kwargs = {k: v for k, v in call.data.items() if k != "entry_id"}

        for eid, entry_data in hass.data[DOMAIN].items():
            if not isinstance(entry_data["provider"], WordOfDayProvider):
                continue
            if entry_id is not None and eid != entry_id:
                continue
            result = await entry_data["provider"].async_render(**kwargs)
            _push_entity_updates(entry_data["entities"])
            return result

        _LOGGER.warning("render_word_of_day: no matching Word of the Day entry found")
        return {}

    async def handle_render_today_in_history(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data.get("entry_id")
        kwargs = {k: v for k, v in call.data.items() if k != "entry_id"}

        for eid, entry_data in hass.data[DOMAIN].items():
            if not isinstance(entry_data["provider"], TodayInHistoryProvider):
                continue
            if entry_id is not None and eid != entry_id:
                continue
            result = await entry_data["provider"].async_render(**kwargs)
            _push_entity_updates(entry_data["entities"])
            return result

        _LOGGER.warning("render_today_in_history: no matching Today in History entry found")
        return {}

    hass.services.async_register(
        DOMAIN,
        "render_now_playing",
        handle_render_now_playing,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "render_saints_day",
        handle_render_saints_day,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "render_word_of_day",
        handle_render_word_of_day,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "render_today_in_history",
        handle_render_today_in_history,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _push_entity_updates(entities: list) -> None:
    """Push updated state to all entities for a given entry."""
    for entity in entities:
        entity.async_write_ha_state()
