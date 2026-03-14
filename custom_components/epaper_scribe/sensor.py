"""Sensor platform for E-Paper Scribe — N entities per config entry."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    provider = entry_data["provider"]
    entities = [
        EpaperScribeSensor(entry, provider, sensor_desc)
        for sensor_desc in provider.SENSORS
    ]
    entry_data["entities"].extend(entities)
    async_add_entities(entities)


class EpaperScribeSensor(SensorEntity):
    """Sensor exposing a single metadata field from the most recent render."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, provider, sensor_desc) -> None:
        self._provider = provider
        self._entry = entry
        self._sensor_desc = sensor_desc
        self._attr_unique_id = f"{entry.entry_id}_{sensor_desc.key}"
        self._attr_name = sensor_desc.name
        self._attr_icon = sensor_desc.icon

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "E-Paper Scribe",
        }

    @property
    def native_value(self):
        return self._provider.sensor_data.get(self._sensor_desc.key)
