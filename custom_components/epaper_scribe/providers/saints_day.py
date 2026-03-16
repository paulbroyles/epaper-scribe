"""Liturgical Calendar / Saints Day content provider for E-Paper Scribe."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    CONF_CALENDAR_TYPE,
    CONF_DEFAULT_SIZE,
    CONF_PALETTE,
    PALETTE_BWR,
    WWW_PATH,
)
from ..dither import async_dither, make_placeholder
from . import ContentProvider, SensorDescription

_LOGGER = logging.getLogger(__name__)

CALENDAR_ANGLICAN = "anglican"
CALENDAR_CATHOLIC = "catholic"

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"

ORDINALS: dict[str, str] = {
    "1": "First", "2": "Second", "3": "Third", "4": "Fourth",
    "5": "Fifth", "6": "Sixth", "7": "Seventh", "8": "Eighth",
    "9": "Ninth", "10": "Tenth", "11": "Eleventh", "12": "Twelfth",
}

SEASON_DESCRIPTIONS: dict[str, str] = {
    "Lent": "A season of fasting, prayer, and almsgiving in preparation for Easter.",
    "Advent": "A season of hopeful waiting and preparation for the coming of Christ.",
    "Christmas": "A season celebrating the birth of Jesus Christ.",
    "Easter": "A season of joy celebrating the resurrection of Jesus Christ.",
    "Epiphany": "A season celebrating the manifestation of Christ to the world.",
    "Ordinary": "Ordinary Time: the season of the Church's daily life and growth.",
}

SENSORS = [
    SensorDescription("saint_name", "Saint Name", "mdi:account-star"),
    SensorDescription("saint_role", "Saint Role", "mdi:account-badge"),
    SensorDescription("season", "Season", "mdi:calendar-star"),
    SensorDescription("week", "Week", "mdi:calendar-week"),
    SensorDescription("description", "Description", "mdi:text"),
    SensorDescription("season_description", "Season Description", "mdi:text-box"),
    SensorDescription("has_saint", "Has Saint", "mdi:check-circle"),
]


class SaintsDayProvider(ContentProvider):
    PROVIDER_TYPE = "saints_day"
    PROVIDER_NAME = "Liturgical Calendar"
    SENSORS = SENSORS

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._cached_date: date | None = None
        self._cached_data: dict[str, Any] | None = None

    @staticmethod
    def get_config_schema() -> dict:
        return {
            vol.Optional(CONF_CALENDAR_TYPE, default=CALENDAR_ANGLICAN): vol.In(
                [CALENDAR_ANGLICAN, CALENDAR_CATHOLIC]
            ),
            vol.Optional(CONF_PALETTE, default=PALETTE_BWR): vol.In(
                ["bw", "bwr", "bwry"]
            ),
            vol.Optional(CONF_DEFAULT_SIZE, default="64x64"): str,
        }

    @staticmethod
    def get_service_schema() -> dict:
        return {
            vol.Optional("force_refresh", default=False): bool,
            vol.Optional("size"): str,
        }

    async def async_render(self, **kwargs) -> dict[str, Any]:
        force_refresh: bool = kwargs.get("force_refresh", False)
        size_str: str = kwargs.get("size", self.config.get(CONF_DEFAULT_SIZE, "64x64"))
        palette: str = self.config.get(CONF_PALETTE, PALETTE_BWR)
        size = _parse_size(size_str)
        today = date.today()

        if (
            not force_refresh
            and self._cached_date == today
            and self._cached_data is not None
        ):
            _LOGGER.debug("Using cached saint data for %s", today)
            return self._cached_data

        calendar_type = self.config.get(CONF_CALENDAR_TYPE, CALENDAR_ANGLICAN)
        saint_name, saint_role, season, week, wiki_url = await self._fetch_calendar(
            calendar_type, today
        )

        has_saint = bool(saint_name)
        description = ""
        image_bytes: bytes | None = None

        if has_saint:
            description, image_url = await self._fetch_wikipedia(
                saint_name, wiki_url or ""
            )
            if image_url:
                image_bytes = await self._fetch_image(image_url)

        if image_bytes:
            dithered = await async_dither(self.hass, image_bytes, size, palette)
        else:
            dithered = make_placeholder(size, (180, 160, 140))

        filename = f"saints_day_artwork_{size[1]}.png"
        await _write_static_file(self.hass, filename, dithered)

        self._image_bytes = dithered
        self._image_last_updated = datetime.now()

        data: dict[str, Any] = {
            "saint_name": saint_name or "",
            "saint_role": saint_role or "",
            "season": season or "",
            "week": _format_week(week) if week else "",
            "description": description,
            "season_description": _get_season_description(season),
            "has_saint": has_saint,
        }
        self._sensor_data = data
        self._cached_date = today
        self._cached_data = data

        _LOGGER.debug(
            "Saints day rendered: %s (has_saint=%s, season=%s)",
            saint_name,
            has_saint,
            season,
        )
        return data

    async def _fetch_calendar(
        self, calendar_type: str, today: date
    ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        if calendar_type == CALENDAR_ANGLICAN:
            return await self.hass.async_add_executor_job(
                _fetch_saint_anglican, today
            )
        _LOGGER.warning("Calendar type '%s' not implemented", calendar_type)
        return None, None, None, None, None

    async def _fetch_wikipedia(
        self, search_term: str, wiki_url: str
    ) -> tuple[str, str]:
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}

            if wiki_url and "/wiki/" in wiki_url:
                page_title = wiki_url.split("/wiki/")[-1]
                api_url = WIKIPEDIA_API + page_title
            else:
                api_url = WIKIPEDIA_API + quote(search_term)

            async with session.get(api_url, headers=headers) as resp:
                if resp.status == 404:
                    fallback_url = WIKIPEDIA_API + quote("Saint " + search_term)
                    async with session.get(fallback_url, headers=headers) as resp2:
                        if resp2.status != 200:
                            return "", ""
                        data = await resp2.json()
                elif resp.status != 200:
                    return "", ""
                else:
                    data = await resp.json()

            extract = data.get("extract", "")
            sentences = extract.split(". ")
            description = sentences[0].strip()
            if description and not description.endswith("."):
                description += "."

            thumbnail = data.get("thumbnail", {})
            image_url = thumbnail.get("source", "")
            return description, image_url

        except Exception as exc:
            _LOGGER.warning("Wikipedia fetch failed for '%s': %s", search_term, exc)
            return "", ""

    async def _fetch_image(self, image_url: str) -> bytes | None:
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            async with session.get(image_url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as exc:
            _LOGGER.warning("Saint image fetch failed: %s", exc)
        return None


def _fetch_saint_anglican(
    today: date,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Fetch today's saint from the Anglican liturgical calendar pip package.

    Runs synchronously — must be called via async_add_executor_job.
    """
    try:
        from liturgical_calendar.liturgical import liturgical_calendar

        day = liturgical_calendar(today)

        raw_name: str = day.get("name", "")
        season: str = day.get("season", "")
        week: str = day.get("week", "")
        wiki_url: str = day.get("url", "")

        if not raw_name:
            return None, None, season, week, wiki_url

        name, role = _parse_saint_title(raw_name)
        return name, role, season, week, wiki_url

    except Exception as exc:
        _LOGGER.warning("Anglican calendar lookup failed: %s", exc)
        return None, None, None, None, None


def _parse_saint_title(title: str) -> tuple[str, str]:
    """Split 'Thomas Aquinas, Doctor of the Church' into (name, role)."""
    name = title
    role = ""

    if "," in title:
        parts = title.split(",", 1)
        name = parts[0].strip()
        role = parts[1].strip()

    for prefix in ("Saint ", "Blessed ", "Venerable ", "Our Lady of "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    return name, role


def _get_season_description(season: str | None) -> str:
    """Return a short description for the current liturgical season."""
    if not season:
        return SEASON_DESCRIPTIONS["Ordinary"]
    for key in SEASON_DESCRIPTIONS:
        if key.lower() in season.lower():
            return SEASON_DESCRIPTIONS[key]
    return SEASON_DESCRIPTIONS["Ordinary"]


def _format_week(week: str) -> str:
    """Convert 'Lent 3' to 'Third Week of Lent'."""
    if not week:
        return week
    parts = week.strip().split()
    if len(parts) == 2:
        season_name, number = parts[0], parts[1]
        ordinal = ORDINALS.get(number, number)
        return f"{ordinal} Week of {season_name}"
    return week


def _parse_size(size_str: str) -> tuple[int, int]:
    """Parse '64x64' into (64, 64). Defaults to 64x64 on error."""
    try:
        w, h = size_str.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 64, 64


async def _write_static_file(hass, filename: str, data: bytes) -> None:
    """Write data to /config/www/epaper_scribe/<filename> in executor."""

    def _write() -> None:
        os.makedirs(WWW_PATH, exist_ok=True)
        path = os.path.join(WWW_PATH, filename)
        with open(path, "wb") as f:
            f.write(data)

    await hass.async_add_executor_job(_write)
