"""Word of the Day content provider for E-Paper Scribe.

Uses the Wordnik Word of the Day API to surface genuinely interesting,
curated vocabulary words with definitions, examples, and notes.

Results are cached per-day; use force_refresh=True or supply a word override
to bypass the cache. A word override always bypasses the cache.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    CONF_API_KEY,
    CONF_DEFAULT_SIZE,
    CONF_PALETTE,
    PALETTE_BWR,
    WWW_PATH,
)
from ..dither import make_placeholder
from . import ContentProvider, SensorDescription

_LOGGER = logging.getLogger(__name__)

WORDNIK_WOTD_URL = "https://api.wordnik.com/v4/words.json/wordOfTheDay"
WORDNIK_WORD_URL = "https://api.wordnik.com/v4/word.json/{word}/definitions"

SENSORS = [
    SensorDescription("word", "Word", "mdi:alphabetical"),
    SensorDescription("part_of_speech", "Part of Speech", "mdi:book-alphabet"),
    SensorDescription("definition", "Definition", "mdi:book-open-variant"),
    SensorDescription("example", "Example", "mdi:format-quote-open"),
    SensorDescription("note", "Note", "mdi:note-text"),
]


class WordOfDayProvider(ContentProvider):
    PROVIDER_TYPE = "word_of_day"
    PROVIDER_NAME = "Word of the Day"
    SENSORS = SENSORS

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._cached_date: date | None = None
        self._cached_data: dict[str, Any] | None = None

    @staticmethod
    def get_config_schema() -> dict:
        return {
            vol.Required(CONF_API_KEY): str,
            vol.Optional(CONF_PALETTE, default=PALETTE_BWR): vol.In(
                ["bw", "bwr", "bwry"]
            ),
            vol.Optional(CONF_DEFAULT_SIZE, default="296x128"): str,
        }

    @staticmethod
    def get_service_schema() -> dict:
        return {
            vol.Optional("force_refresh", default=False): bool,
            vol.Optional("word"): str,
        }

    async def async_render(self, **kwargs) -> dict[str, Any]:
        force_refresh: bool = kwargs.get("force_refresh", False)
        override_word: str | None = kwargs.get("word")
        size = _parse_size(self.config.get(CONF_DEFAULT_SIZE, "296x128"))
        api_key: str = self.config.get(CONF_API_KEY, "")
        today = date.today()

        if (
            not force_refresh
            and override_word is None
            and self._cached_date == today
            and self._cached_data is not None
        ):
            _LOGGER.debug("Using cached word of the day for %s", today)
            return self._cached_data

        if override_word:
            result = await self._fetch_word_definitions(override_word, api_key)
        else:
            result = await self._fetch_word_of_day(today, api_key)

        dithered = make_placeholder(size, (245, 240, 230))
        filename = f"word_of_day_{size[1]}.png"
        await _write_static_file(self.hass, filename, dithered)

        self._image_bytes = dithered
        self._image_last_updated = datetime.now()

        data: dict[str, Any] = {
            "word": result.get("word", ""),
            "part_of_speech": result.get("part_of_speech", ""),
            "definition": result.get("definition", ""),
            "example": result.get("example", ""),
            "note": result.get("note", ""),
        }
        self._sensor_data = data

        if override_word is None:
            self._cached_date = today
            self._cached_data = data

        _LOGGER.debug(
            "Word of the day rendered: %s (%s)", data["word"], data["part_of_speech"]
        )
        return data

    async def _fetch_word_of_day(
        self, today: date, api_key: str
    ) -> dict[str, Any]:
        """Fetch today's Wordnik Word of the Day."""
        try:
            session = async_get_clientsession(self.hass)
            params = {
                "date": today.isoformat(),
                "api_key": api_key,
            }
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}

            async with session.get(
                WORDNIK_WOTD_URL, params=params, headers=headers
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Wordnik WOTD API returned %s", resp.status
                    )
                    return _empty_result()

                data = await resp.json()

            return _parse_wotd_response(data)

        except Exception as exc:
            _LOGGER.warning("Failed to fetch Wordnik word of the day: %s", exc)
            return _empty_result()

    async def _fetch_word_definitions(
        self, word: str, api_key: str
    ) -> dict[str, Any]:
        """Fetch definitions for a specific word override."""
        try:
            session = async_get_clientsession(self.hass)
            params = {
                "limit": 1,
                "includeRelated": "false",
                "useCanonical": "true",
                "includeTags": "false",
                "api_key": api_key,
            }
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            url = WORDNIK_WORD_URL.format(word=word)

            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Wordnik definitions API returned %s for '%s'",
                        resp.status,
                        word,
                    )
                    return {"word": word, **_empty_result()}

                data = await resp.json()

            if not data:
                return {"word": word, **_empty_result()}

            first = data[0]
            return {
                "word": word,
                "part_of_speech": first.get("partOfSpeech", ""),
                "definition": first.get("text", ""),
                "example": "",
                "note": "",
            }

        except Exception as exc:
            _LOGGER.warning(
                "Failed to fetch Wordnik definition for '%s': %s", word, exc
            )
            return {"word": word, **_empty_result()}


def _parse_wotd_response(data: dict) -> dict[str, Any]:
    """Extract fields from a Wordnik WOTD API response."""
    word = data.get("word", "")

    definitions = data.get("definitions") or []
    part_of_speech = ""
    definition = ""
    if definitions:
        first_def = definitions[0]
        part_of_speech = first_def.get("partOfSpeech", "")
        definition = first_def.get("text", "")

    examples = data.get("examples") or []
    example = examples[0].get("text", "") if examples else ""

    note = data.get("note", "")

    return {
        "word": word,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "example": example,
        "note": note,
    }


def _empty_result() -> dict[str, Any]:
    return {
        "word": "",
        "part_of_speech": "",
        "definition": "",
        "example": "",
        "note": "",
    }


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
