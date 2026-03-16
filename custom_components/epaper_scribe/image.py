"""Image platform for E-Paper Scribe — one entity per config entry."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    provider = entry_data["provider"]
    entity = EpaperScribeImageEntity(hass, entry, provider)
    entry_data["entities"].append(entity)
    async_add_entities([entity])


class EpaperScribeImageEntity(ImageEntity):
    """Image entity showing the most recently dithered artwork.

    Marked DIAGNOSTIC so it doesn't auto-appear as a dashboard card.
    Users can add it to a dashboard manually when they want a preview.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, provider) -> None:
        super().__init__(hass)
        self._provider = provider
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_artwork"
        self._attr_name = "Artwork"
        self._attr_content_type = "image/png"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "E-Paper Scribe",
        }

    @property
    def image_last_updated(self) -> datetime | None:
        return self._provider.image_last_updated

    async def async_image(self) -> bytes | None:
        return self._provider.image_bytes
