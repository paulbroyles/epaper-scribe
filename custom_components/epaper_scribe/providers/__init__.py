"""Content provider abstract base class for E-Paper Scribe."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SensorDescription:
    """Describes a sensor entity a provider exposes."""

    key: str
    name: str
    icon: str | None = None


class ContentProvider(ABC):
    """Base class for all content providers.

    Adding a new provider = one new file in providers/, registered in
    PROVIDER_REGISTRY. No changes to image.py, sensor.py, __init__.py,
    or config_flow.py needed.
    """

    PROVIDER_TYPE: str = ""
    PROVIDER_NAME: str = ""
    SENSORS: list[SensorDescription] = []

    def __init__(self, hass, config: dict) -> None:
        self.hass = hass
        self.config = config
        self._image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        self._sensor_data: dict[str, Any] = {}

    @abstractmethod
    async def async_render(self, **kwargs) -> dict:
        """Fetch data, dither image, update sensor data, return metadata dict."""

    @staticmethod
    @abstractmethod
    def get_config_schema() -> dict:
        """Return a plain dict of {vol.Required/Optional key: validator} for config flow."""

    @staticmethod
    @abstractmethod
    def get_service_schema() -> dict:
        """Return a plain dict of {vol.Optional key: validator} for service calls."""

    @property
    def image_bytes(self) -> bytes | None:
        return self._image_bytes

    @property
    def image_last_updated(self) -> datetime | None:
        return self._image_last_updated

    @property
    def sensor_data(self) -> dict[str, Any]:
        return self._sensor_data
