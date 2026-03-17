"""Now Playing content provider for E-Paper Scribe."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
import homeassistant.helpers.config_validation as cv

from ..const import (
    CONF_DEFAULT_SIZE,
    CONF_MEDIA_PLAYER_ENTITY,
    CONF_PALETTE,
    PALETTE_BWR,
)
from ..dither import async_render_to_file
from . import ContentProvider, SensorDescription

_LOGGER = logging.getLogger(__name__)

SENSORS = [
    SensorDescription("state", "State", "mdi:play-circle"),
    SensorDescription("creator", "Creator", "mdi:account-music"),
    SensorDescription("title", "Title", "mdi:music-note"),
    SensorDescription("container", "Container", "mdi:album"),
    SensorDescription("content_type", "Content Type", "mdi:format-list-bulleted-type"),
]


class NowPlayingProvider(ContentProvider):
    PROVIDER_TYPE = "now_playing"
    PROVIDER_NAME = "Now Playing"
    SENSORS = SENSORS

    @staticmethod
    def get_config_schema() -> dict:
        return {
            vol.Required(CONF_MEDIA_PLAYER_ENTITY): cv.entity_id,
            vol.Optional(CONF_PALETTE, default=PALETTE_BWR): vol.In(["bw", "bwr", "bwry"]),
            vol.Optional(CONF_DEFAULT_SIZE, default="128x128"): str,
        }

    @staticmethod
    def get_service_schema() -> dict:
        return {
            vol.Optional(CONF_MEDIA_PLAYER_ENTITY): cv.entity_id,
            vol.Optional("size"): str,
        }

    async def async_render(self, **kwargs) -> dict[str, Any]:
        entity_id = kwargs.get(
            CONF_MEDIA_PLAYER_ENTITY,
            self.config.get(CONF_MEDIA_PLAYER_ENTITY),
        )
        size_str = kwargs.get("size", self.config.get(CONF_DEFAULT_SIZE, "128x128"))
        palette = self.config.get(CONF_PALETTE, PALETTE_BWR)
        size = _parse_size(size_str)

        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            _LOGGER.warning("Media player entity %s not found", entity_id)
            return {}

        player_state = state_obj.state
        attrs = state_obj.attributes
        content_type = attrs.get("media_content_type", "")

        # Semantic field mapping (ported from templates.yaml)
        if content_type == "tvshow":
            creator = attrs.get("media_series_title", "")
            container = attrs.get("media_series_title", "")
        elif content_type == "music":
            creator = attrs.get("media_album_artist") or attrs.get("media_artist", "")
            container = attrs.get("media_album_name", "")
        elif content_type == "podcast":
            creator = attrs.get("media_album_name", "")
            container = (
                attrs.get("media_artist") or attrs.get("media_album_name", "")
            )
        elif content_type == "movie":
            creator = attrs.get("media_artist", "")
            container = ""
        else:
            creator = attrs.get("media_artist", "")
            container = attrs.get("media_album_name", "")

        title = attrs.get("media_title", "")

        image_bytes = await _fetch_media_image(self.hass, entity_id)
        filename = f"now_playing_artwork_{size[1]}.png"
        await async_render_to_file(self.hass, filename, image_bytes, size, palette)

        self._image_bytes = image_bytes
        self._image_last_updated = datetime.now()
        self._sensor_data = {
            "state": player_state,
            "creator": creator,
            "title": title,
            "container": container,
            "content_type": content_type,
        }

        _LOGGER.debug(
            "Now playing rendered: %s — %s (%s)", creator, title, container
        )
        return self._sensor_data


async def _fetch_media_image(hass, entity_id: str) -> bytes | None:
    """Fetch artwork bytes via HA's internal media_player API.

    Uses async_get_media_image() on the entity object directly — no HTTP
    request or long-lived access token required.
    """
    try:
        from homeassistant.helpers.entity_component import DATA_INSTANCES

        entity_comp = hass.data.get(DATA_INSTANCES, {}).get(MP_DOMAIN)
        if entity_comp is None:
            _LOGGER.warning("Media player entity component not found in hass.data")
            return None

        player = entity_comp.get_entity(entity_id)
        if player is None:
            _LOGGER.warning(
                "Media player entity %s not found in component", entity_id
            )
            return None

        image_bytes, _content_type = await player.async_get_media_image()
        return image_bytes
    except Exception as exc:
        _LOGGER.warning("Failed to fetch media image for %s: %s", entity_id, exc)
        return None


def _parse_size(size_str: str) -> tuple[int, int]:
    """Parse '128x128' into (128, 128). Defaults to 128x128 on error."""
    try:
        w, h = size_str.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 128, 128
