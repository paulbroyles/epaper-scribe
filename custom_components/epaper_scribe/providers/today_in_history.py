"""Today in History content provider for E-Paper Scribe.

Uses the Wikipedia "On This Day" feed API (no key required) to surface a
historical event that occurred on today's date. A different event is chosen
each calendar year, deterministically. Results are cached per-day.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    CONF_DEFAULT_SIZE,
    CONF_PALETTE,
    PALETTE_BWR,
    WWW_PATH,
)
from ..dither import async_dither, make_placeholder
from . import ContentProvider, SensorDescription

_LOGGER = logging.getLogger(__name__)

WIKIPEDIA_ONTHISDAY_URL = (
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
)
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

SENSORS = [
    SensorDescription("year", "Year", "mdi:calendar-clock"),
    SensorDescription("event", "Event", "mdi:text"),
    SensorDescription("page_title", "Article", "mdi:wikipedia"),
    SensorDescription("has_image", "Has Image", "mdi:image"),
]


class TodayInHistoryProvider(ContentProvider):
    PROVIDER_TYPE = "today_in_history"
    PROVIDER_NAME = "Today in History"
    SENSORS = SENSORS

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._cached_date: date | None = None
        self._cached_data: dict[str, Any] | None = None

    @staticmethod
    def get_config_schema() -> dict:
        return {
            vol.Optional(CONF_PALETTE, default=PALETTE_BWR): vol.In(
                ["bw", "bwr", "bwry"]
            ),
            vol.Optional(CONF_DEFAULT_SIZE, default="296x128"): str,
        }

    @staticmethod
    def get_service_schema() -> dict:
        return {
            vol.Optional("force_refresh", default=False): bool,
        }

    async def async_render(self, **kwargs) -> dict[str, Any]:
        force_refresh: bool = kwargs.get("force_refresh", False)
        size_str: str = self.config.get(CONF_DEFAULT_SIZE, "296x128")
        palette: str = self.config.get(CONF_PALETTE, PALETTE_BWR)
        size = _parse_size(size_str)
        today = date.today()

        if (
            not force_refresh
            and self._cached_date == today
            and self._cached_data is not None
        ):
            _LOGGER.debug("Using cached today-in-history for %s", today)
            return self._cached_data

        filename = f"today_in_history_{size[1]}.png"

        # Write placeholder immediately so the file always exists even if
        # the image fetch or dither fails later.
        await _write_static_file(self.hass, filename, make_placeholder(size, (200, 195, 185)))

        event_year, event_text, page_title, image_url = await self._fetch_event(today)

        dithered: bytes | None = None
        if image_url:
            image_bytes = await self._fetch_image(image_url)
            if image_bytes:
                try:
                    dithered = await async_dither(self.hass, image_bytes, size, palette)
                except Exception as exc:
                    _LOGGER.warning("Failed to dither today-in-history image: %s", exc)

        if dithered:
            await _write_static_file(self.hass, filename, dithered)
        else:
            image_url = ""  # no real image rendered; placeholder already on disk

        self._image_bytes = dithered
        self._image_last_updated = datetime.now()

        data: dict[str, Any] = {
            "year": str(event_year) if event_year else "",
            "event": event_text,
            "page_title": page_title,
            "has_image": bool(image_url),
        }
        self._sensor_data = data
        self._cached_date = today
        self._cached_data = data

        _LOGGER.debug(
            "Today in history rendered: %s — %s", event_year, event_text[:60]
        )
        return data

    async def _fetch_event(
        self, today: date
    ) -> tuple[int | None, str, str, str]:
        """Return (year, event_text, page_title, image_url) for a chosen event."""
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            url = WIKIPEDIA_ONTHISDAY_URL.format(
                month=today.month, day=today.day
            )

            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Wikipedia On This Day API returned %s", resp.status
                    )
                    return None, "", "", ""
                data = await resp.json()

            events = data.get("events", [])
            if not events:
                return None, "", "", ""

            # Pick deterministically: rotate by year so each year surfaces a
            # different event, but the same event all day.
            idx = today.year % len(events)
            chosen = events[idx]

            year: int = chosen.get("year", 0)
            text: str = chosen.get("text", "")

            # Find the first page with a thumbnail for the image.
            page_title = ""
            image_url = ""
            for page in chosen.get("pages", []):
                thumbnail = page.get("thumbnail") or page.get("originalimage")
                if thumbnail and thumbnail.get("source"):
                    page_title = page.get("title", "")
                    image_url = thumbnail["source"]
                    break
                if not page_title:
                    page_title = page.get("title", "")

            return year, text, page_title, image_url

        except Exception as exc:
            _LOGGER.warning("Wikipedia On This Day fetch failed: %s", exc)
            return None, "", "", ""

    async def _fetch_image(self, image_url: str) -> bytes | None:
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            async with session.get(image_url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as exc:
            _LOGGER.warning("Today-in-history image fetch failed: %s", exc)
        return None


def _parse_size(size_str: str) -> tuple[int, int]:
    try:
        w, h = size_str.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 296, 128


async def _write_static_file(hass, filename: str, data: bytes) -> None:
    def _write() -> None:
        os.makedirs(WWW_PATH, exist_ok=True)
        path = os.path.join(WWW_PATH, filename)
        with open(path, "wb") as f:
            f.write(data)

    await hass.async_add_executor_job(_write)
