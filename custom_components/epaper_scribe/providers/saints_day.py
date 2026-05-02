"""Liturgical Calendar / Saints Day content provider for E-Paper Scribe."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, unquote

import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    CONF_CALENDAR_TYPE,
    CONF_DEFAULT_SIZE,
    CONF_FONT_PATH,
    CONF_NAME_FONT_PATH,
    CONF_PALETTE,
    PALETTE_BWR,
)
from ..dither import async_render_to_file
from . import ContentProvider, SensorDescription
from .catholic_calendar import get_catholic_feasts
from .combined_calendar import (
    AnglicanDay,
    CombinedResult,
    _CrossDateFlags,
    build_year_cache,
    get_combined_result,
)

_LOGGER = logging.getLogger(__name__)

CALENDAR_ANGLICAN = "anglican"
CALENDAR_CATHOLIC = "catholic"
CALENDAR_COMBINED = "combined"

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKIPEDIA_MW_API = "https://en.wikipedia.org/w/api.php"

ORDINALS: dict[str, str] = {
    "1": "First", "2": "Second", "3": "Third", "4": "Fourth",
    "5": "Fifth", "6": "Sixth", "7": "Seventh", "8": "Eighth",
    "9": "Ninth", "10": "Tenth", "11": "Eleventh", "12": "Twelfth",
}

SEASON_DESCRIPTIONS: dict[str, str] = {
    "Advent": (
        "Advent opens the liturgical year with four weeks of watchful waiting. "
        "The Church holds its lamp ready in the dark, preparing for the coming of Christ at Christmas "
        "and looking forward in hope to his final return in glory."
    ),
    "Christmas": (
        "Christmas is a twelve-day season celebrating the incarnation: the eternal Word made flesh. "
        "God enters human history in Jesus of Nazareth, born of Mary, "
        "light arriving in the world's darkness."
    ),
    "Epiphany": (
        "Epiphany — from the Greek for 'manifestation' — celebrates the revealing of Christ to all nations. "
        "The season stretches from the visit of the Magi through the weeks that unfold who Jesus is: "
        "baptized in the Jordan, turning water to wine, transfigured on the mountain."
    ),
    "before Lent": (
        "The Sundays before Lent are an ancient transitional season, known in older usage as the Gesima Sundays. "
        "The Church begins to turn toward fasting and self-examination, "
        "though the full Lenten fast has not yet begun."
    ),
    "Lent": (
        "Lent is forty days of prayer, fasting, and almsgiving from Ash Wednesday to Holy Saturday. "
        "In imitation of Jesus's forty days in the wilderness, "
        "the Church undertakes a discipline of repentance and return to God."
    ),
    "Holy Week": (
        "Holy Week encompasses the most solemn days of the year. "
        "It begins with the palms and acclamations of Palm Sunday and moves through the Last Supper, "
        "the crucifixion on Good Friday, and the long vigil of Holy Saturday."
    ),
    "Easter": (
        "The Great Fifty Days of Easter are the chief festival of the Christian year. "
        "The Church celebrates the resurrection of Jesus from the dead — death defeated, new life poured out. "
        "Alleluia marks every prayer of this season of joy."
    ),
    "Pentecost": (
        "Pentecost marks the descent of the Holy Spirit upon the apostles in Jerusalem, "
        "fifty days after Easter. Wind and fire, the Spirit transforms a frightened gathering "
        "into the Church of God. Many traditions call this day the birthday of the Church."
    ),
    "Trinity": (
        "Trinity Sunday opens the longest season of the liturgical year, running through summer and autumn. "
        "Ordinary Time is not unimportant — it is the season of daily faithfulness, "
        "the Church living out in the world what it has celebrated at the font and table."
    ),
    "before Advent": (
        "The weeks before Advent close the liturgical year with an eschatological focus. "
        "All Saints, All Souls, and the feast of Christ the King mark this season. "
        "The Church looks beyond the present toward the Kingdom that is coming — "
        "the final restoration of all things."
    ),
}

SENSORS = [
    SensorDescription("saint_name", "Saint Name", "mdi:account-star"),
    SensorDescription("saint_role", "Saint Role", "mdi:account-badge"),
    SensorDescription("season", "Season", "mdi:calendar-star"),
    SensorDescription("week", "Week", "mdi:calendar-week"),
    SensorDescription("description", "Description", "mdi:text"),
    SensorDescription("season_description", "Season Description", "mdi:text-box"),
    SensorDescription("has_saint", "Has Saint", "mdi:check-circle"),
    SensorDescription("calendar_source", "Calendar Source", "mdi:book-cross"),
    SensorDescription("calendar_flag", "Calendar Flag", "mdi:flag"),
]


class SaintsDayProvider(ContentProvider):
    PROVIDER_TYPE = "saints_day"
    PROVIDER_NAME = "Liturgical Calendar"
    SENSORS = SENSORS

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._cached_date: date | None = None
        self._cached_data: dict[str, Any] | None = None
        # Combined mode: cache the full Anglican data + flags for a year
        self._year_cache_year: int | None = None
        self._year_cache_ang: dict[str, AnglicanDay] | None = None
        self._year_cache_flags: _CrossDateFlags | None = None

    async def async_initialize(self) -> None:
        size = _parse_size(self.config.get(CONF_DEFAULT_SIZE, "64x64"))
        await async_render_to_file(
            self.hass,
            f"saints_day_artwork_{size[1]}.png",
            None,
            size,
            placeholder_color=(180, 160, 140),
        )

    @staticmethod
    def get_config_schema() -> dict:
        return {
            vol.Optional(CONF_CALENDAR_TYPE, default=CALENDAR_COMBINED): vol.In(
                [CALENDAR_ANGLICAN, CALENDAR_CATHOLIC, CALENDAR_COMBINED]
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
            return self._cached_data

        calendar_type = self.config.get(CONF_CALENDAR_TYPE, CALENDAR_COMBINED)

        if calendar_type == CALENDAR_COMBINED:
            data = await self._render_combined(today, size, palette)
        elif calendar_type == CALENDAR_ANGLICAN:
            data = await self._render_anglican(today, size, palette)
        else:
            _LOGGER.warning("Calendar type '%s' not implemented", calendar_type)
            return {}

        self._sensor_data = data
        self._cached_date = today
        self._cached_data = data
        return data

    # ------------------------------------------------------------------
    # Combined mode
    # ------------------------------------------------------------------

    async def _render_combined(
        self, today: date, size: tuple[int, int], palette: str
    ) -> dict[str, Any]:
        # Ensure year cache is populated
        if self._year_cache_year != today.year:
            await self._build_year_cache(today.year)

        ang_day = self._year_cache_ang.get(today.isoformat())
        if ang_day is None:
            ang_day = AnglicanDay(name="", week="", season="Ordinary", type_="", wiki_url="")

        result: CombinedResult = await self.hass.async_add_executor_job(
            get_combined_result, today, ang_day, self._year_cache_flags
        )

        saint_name = ""
        saint_role = ""
        description = ""
        image_bytes: bytes | None = None

        parsed = None
        if result.source != "none" and result.display_name:
            from ..saint_name import parse_saint_name
            parsed = parse_saint_name(result.display_name)
            saint_role_parts = [s.descriptor for s in parsed.segments if s.descriptor]
            saint_name = " · ".join(s.name for s in parsed.segments) if parsed.segments else result.display_name
            saint_role = " · ".join(saint_role_parts)

            names = [s.name for s in parsed.segments] if parsed.segments else [result.display_name]
            descs = [s.descriptor for s in parsed.segments] if parsed.segments else []
            description, image_url = await self._fetch_wikipedia(names, result.wiki_url, descs)
            if image_url:
                image_bytes = await self._fetch_image(image_url)

        font_path = self.config.get(CONF_FONT_PATH)
        name_font_path = self.config.get(CONF_NAME_FONT_PATH)
        season_desc = _get_season_description(result.season)
        ang_type = result.anglican.type_ if result.anglican else ""
        cat_feasts_today = await self.hass.async_add_executor_job(get_catholic_feasts, today)
        calendar_tag = _compute_calendar_tag(result, cat_feasts_today, ang_type) if saint_name else ""
        composed = await self.hass.async_add_executor_job(
            _compose_image,
            size,
            parsed,
            result.season or "",
            _format_week(result.week) if result.week else "",
            description if saint_name else season_desc,
            image_bytes,
            font_path,
            name_font_path,
            calendar_tag,
        )

        filename = f"saints_day_artwork_{size[1]}.png"
        await async_render_to_file(
            self.hass, filename, composed, size, palette, (180, 160, 140)
        )
        self._image_bytes = composed
        self._image_last_updated = datetime.now()

        return {
            "saint_name": saint_name,
            "saint_role": saint_role,
            "season": result.season or "",
            "week": _format_week(result.week) if result.week else "",
            "description": description,
            "season_description": _get_season_description(result.season),
            "has_saint": bool(saint_name),
            "calendar_source": result.flag_source if result.flag else "shared",
            "calendar_flag": result.flag,
        }

    async def _build_year_cache(self, year: int) -> None:
        """Fetch the full year of Anglican data and precompute cross-date flags."""
        ang_data: dict[str, AnglicanDay] = await self.hass.async_add_executor_job(
            _fetch_anglican_year, year
        )
        cat_data = await self.hass.async_add_executor_job(
            _fetch_catholic_year, year
        )
        flags = await self.hass.async_add_executor_job(
            build_year_cache, year, ang_data, cat_data
        )
        self._year_cache_year = year
        self._year_cache_ang = ang_data
        self._year_cache_flags = flags

    # ------------------------------------------------------------------
    # Anglican-only mode (original behaviour)
    # ------------------------------------------------------------------

    async def _render_anglican(
        self, today: date, size: tuple[int, int], palette: str
    ) -> dict[str, Any]:
        saint_name, saint_role, season, week, wiki_url, ang_type = (
            await self.hass.async_add_executor_job(_fetch_saint_anglican, today)
        )

        has_saint = bool(saint_name)
        description = ""
        image_bytes: bytes | None = None

        parsed_ang = None
        if has_saint:
            from ..saint_name import parse_saint_name
            parsed_ang = parse_saint_name(saint_name)
            names = [s.name for s in parsed_ang.segments] if parsed_ang.segments else [saint_name]
            descs = [s.descriptor for s in parsed_ang.segments] if parsed_ang.segments else []
            description, image_url = await self._fetch_wikipedia(names, wiki_url or "", descs)
            if image_url:
                image_bytes = await self._fetch_image(image_url)

        font_path = self.config.get(CONF_FONT_PATH)
        name_font_path = self.config.get(CONF_NAME_FONT_PATH)
        season_desc = _get_season_description(season)
        ang_key = (ang_type or "").lower().strip()
        calendar_tag = (
            f"Anglican {_ANG_TYPE_LABELS.get(ang_key, ang_type.title())}".strip()
            if has_saint and ang_type else ""
        )
        composed = await self.hass.async_add_executor_job(
            _compose_image,
            size,
            parsed_ang,
            season or "",
            _format_week(week) if week else "",
            description if has_saint else season_desc,
            image_bytes,
            font_path,
            name_font_path,
            calendar_tag,
        )

        filename = f"saints_day_artwork_{size[1]}.png"
        await async_render_to_file(
            self.hass, filename, composed, size, palette, (180, 160, 140)
        )
        self._image_bytes = composed
        self._image_last_updated = datetime.now()

        return {
            "saint_name": saint_name or "",
            "saint_role": saint_role or "",
            "season": season or "",
            "week": _format_week(week) if week else "",
            "description": description,
            "season_description": _get_season_description(season),
            "has_saint": has_saint,
            "calendar_source": "anglican",
            "calendar_flag": False,
        }

    # ------------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_wikipedia_one(self, search_term: str) -> tuple[str, str]:
        """Fetch the Wikipedia REST summary for *search_term* (a page title).

        Wikipedia follows redirects.  Disambiguation pages are treated as
        failures (returns ("", "")) so the caller can try the next candidate.
        Returns ("", "") on any non-200 status or exception.
        """
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            url = WIKIPEDIA_API + quote(search_term)
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return "", ""
                data = await resp.json()
            if data.get("type") == "disambiguation":
                return "", ""
            return (
                data.get("extract", ""),
                data.get("thumbnail", {}).get("source", ""),
            )
        except Exception as exc:
            _LOGGER.warning("Wikipedia fetch failed for %r: %s", search_term, exc)
            return "", ""

    async def _fetch_wikipedia_url(self, wiki_url: str) -> tuple[str, str]:
        """Fetch Wikipedia summary from a known /wiki/… URL."""
        if "/wiki/" not in wiki_url:
            return "", ""
        # unquote first so we don't double-encode (e.g. %27 → %2527)
        page_title = unquote(wiki_url.split("/wiki/")[-1])
        return await self._fetch_wikipedia_one(page_title)

    async def _fetch_wikipedia(
        self,
        names: list[str],
        wiki_url: str = "",
        descriptors: list[str] | None = None,
    ) -> tuple[str, str]:
        """Fetch a Wikipedia description for one or more saints.

        *names* may include compound entries like "Philip and James"; these are
        expanded into individual people.  *descriptors* are the corresponding
        role words per name segment ("Apostles", "Monk", …).

        Search cascade
        ──────────────
        For *multiple* individuals (including expanded compounds):
          1a. "Saints {name1} and {name2}, {descriptor}"
          1b. "Saints {name1} and {name2}"
          1c. "{name1} and {name2}"
          Each is accepted only if all individuals' first names appear in the
          article text (so Philip-only articles are rejected for Philip+James).

        For each individual (once joint searches fail):
          2a. "Saint {name}, {descriptor}"  (e.g. "Saint Philip, Apostle")
          2b. "Saint {name}"
          2c. "{name}"
          First sentences are combined; first image is used.

        For a *single* name with no expansion:
          Same individual cascade (2a–2c).

        The authoritative *wiki_url* (from the Anglican calendar) is tried
        before any search, but only accepted if it covers all individuals.
        """
        import re as _re

        def _singularize(word: str) -> str:
            """'Apostles' → 'Apostle', 'Bishops' → 'Bishop', etc."""
            skip = {"jesus", "lazarus", "thomas", "status"}
            if word.lower() in skip:
                return word
            if word.lower().endswith("s") and len(word) > 3:
                return word[:-1]
            return word

        # ── Expand compound names ──────────────────────────────────────────
        # ("Philip and James", "Apostles") → [("Philip","Apostles"),("James","Apostles")]
        individuals: list[tuple[str, str]] = []
        for i, name in enumerate(names):
            desc = (descriptors[i] if descriptors and i < len(descriptors) else "") or ""
            if _re.search(r"\band\b", name, _re.IGNORECASE):
                parts = [
                    p.strip()
                    for p in _re.split(r"\s+and\s+", name, flags=_re.IGNORECASE)
                    if p.strip()
                ]
                for p in parts:
                    individuals.append((p, desc))
            else:
                individuals.append((name, desc))

        ind_names = [n for n, _ in individuals]

        def _covers_all(text: str) -> bool:
            tl = text.lower()
            return all(n.split()[0].lower() in tl for n in ind_names)

        # ── 0. Authoritative wiki_url ──────────────────────────────────────
        if wiki_url:
            ex, img = await self._fetch_wikipedia_url(wiki_url)
            if ex and (len(ind_names) == 1 or _covers_all(ex)):
                return ex, img
            # Otherwise fall through — may only cover one person

        if not individuals:
            return "", ""

        # ── 1. Joint cascade (multiple individuals) ────────────────────────
        if len(ind_names) > 1:
            shared_desc = _singularize(individuals[0][1].split()[0]) if individuals[0][1] else ""
            joint_base = " and ".join(ind_names)
            joint_queries: list[str] = []
            if shared_desc:
                joint_queries.append("Saints " + joint_base + ", " + shared_desc)
            joint_queries.append("Saints " + joint_base)
            joint_queries.append(joint_base)

            for q in joint_queries:
                ex, img = await self._fetch_wikipedia_one(q)
                if ex and _covers_all(ex):
                    return ex, img

        # ── 2. Individual cascade ──────────────────────────────────────────
        sentences: list[str] = []
        image_url = ""
        # Track the query that successfully fetched each person's article,
        # so we can later use those articles for companion inference.
        # Seed with the wiki_url article if we have one (even if it only covers
        # some individuals — the parse API can still find companion links in it).
        fetched_queries: list[str] = []
        if wiki_url and "/wiki/" in wiki_url:
            fetched_queries.append(wiki_url.split("/wiki/")[-1])
        pending: list[tuple[str, str]] = []  # (name, desc) for which direct search failed

        for name, desc in individuals:
            desc_word = _singularize(desc.split()[0]) if desc else ""
            candidates: list[str] = []
            if desc_word:
                candidates.append("Saint " + name + ", " + desc_word)
                candidates.append("Saint " + name + " the " + desc_word)
                candidates.append(name + " the " + desc_word)
            candidates.append("Saint " + name)
            candidates.append(name)

            ex = im = ""
            successful_q = ""
            for q in candidates:
                ex, im = await self._fetch_wikipedia_one(q)
                if ex:
                    successful_q = q
                    break

            if ex:
                first = ex.split(". ")[0].strip()
                if not first.endswith("."):
                    first += "."
                sentences.append(first)
                fetched_queries.append(successful_q)
            else:
                pending.append((name, desc))
            if im and not image_url:
                image_url = im

        # ── 3. Companion inference for individuals that direct search missed ─
        # For each failed person, scan the successfully-fetched companions'
        # articles (via the MediaWiki parse API) for wikilinks whose title
        # starts with the failed person's first name.  This handles cases like
        # "Philip and James" where Philip's article explicitly links to
        # [[James the Less]] even though "James the Apostle" is a disambiguation.
        for name, _ in pending:
            ex = im = ""
            for companion_q in fetched_queries:
                links = await self._infer_companion_candidates(companion_q, name.split()[0])
                for link_title in links:
                    ex, im = await self._fetch_wikipedia_one(link_title)
                    if ex:
                        break
                if ex:
                    break
            if ex:
                first = ex.split(". ")[0].strip()
                if not first.endswith("."):
                    first += "."
                sentences.append(first)
            if im and not image_url:
                image_url = im

        if sentences:
            return " ".join(sentences), image_url
        return "", ""

    async def _infer_companion_candidates(
        self, page_query: str, target_first_name: str
    ) -> list[str]:
        """Scan a companion article's text for specific mentions of *target_first_name*.

        Uses the MediaWiki extracts API to retrieve several sentences of the
        article, then extracts qualified name phrases ("James the Less",
        "James, son of Alphaeus", …).  This is more context-accurate than
        the links list, which can contain many unrelated articles sharing the
        same first name.

        Returns a deduplicated list of candidate titles to try, in order of
        appearance in the text.  Returns [] on any failure.
        """
        import re as _re

        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            url = (
                WIKIPEDIA_MW_API
                + "?action=query&prop=extracts&exsentences=15&format=json"
                + "&explaintext=1&redirects=1&titles=" + quote(page_query)
            )
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            pages = data.get("query", {}).get("pages", {})
            text = next(
                (p.get("extract", "") for p in pages.values()), ""
            )
        except Exception as exc:
            _LOGGER.debug("Companion text fetch failed for %r: %s", page_query, exc)
            return []

        if not text:
            return []

        fn = _re.escape(target_first_name.capitalize())
        # Match "James the Less", "James, son of Alphaeus", "James of the Marches", etc.
        pattern = _re.compile(
            r"\b(" + fn
            + r"(?:\s+the\s+\w+|,\s+son\s+of(?:\s+\w+)+|\s+of\s+(?:the\s+)?\w+)"
            r")\b",
            _re.IGNORECASE,
        )
        seen: set[str] = set()
        results: list[str] = []
        for m in pattern.findall(text):
            m = m.strip()
            if m not in seen and m.lower() != target_first_name.lower():
                seen.add(m)
                results.append(m)
        return results

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


# ---------------------------------------------------------------------------
# Synchronous helpers (run in executor)
# ---------------------------------------------------------------------------

def _fetch_anglican_year(year: int) -> dict[str, AnglicanDay]:
    """Return all Anglican days for year as {iso_date: AnglicanDay}."""
    from datetime import timedelta
    from liturgical_calendar.liturgical import liturgical_calendar

    result: dict[str, AnglicanDay] = {}
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        try:
            cal = liturgical_calendar(d)
            result[d.isoformat()] = AnglicanDay(
                name=cal.get("name", ""),
                week=cal.get("week", ""),
                season=cal.get("season", ""),
                type_=cal.get("type", ""),
                wiki_url=cal.get("url", ""),
            )
        except Exception:
            pass
        d += timedelta(days=1)
    return result


def _fetch_catholic_year(year: int) -> dict[str, list]:
    """Return all Catholic feasts for year as {iso_date: [CatholicFeast]}."""
    from datetime import timedelta

    result = {}
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        feasts = get_catholic_feasts(d)
        if feasts:
            result[d.isoformat()] = feasts
        d += timedelta(days=1)
    return result


def _fetch_saint_anglican(
    today: date,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str]:
    """Fetch today's Anglican saint. Runs synchronously.

    Returns (name, role, season, week, wiki_url, type_).
    """
    try:
        from liturgical_calendar.liturgical import liturgical_calendar
        from ..saint_name import parse_saint_name

        day = liturgical_calendar(today)
        raw_name: str = day.get("name", "")
        season: str = day.get("season", "")
        week: str = day.get("week", "")
        wiki_url: str = day.get("url", "")
        type_: str = day.get("type", "")

        if not raw_name:
            return None, None, season, week, wiki_url, type_

        parsed = parse_saint_name(raw_name)
        name = " · ".join(s.name for s in parsed.segments) if parsed.segments else raw_name
        role = " · ".join(s.descriptor for s in parsed.segments if s.descriptor)
        return name, role, season, week, wiki_url, type_

    except Exception as exc:
        _LOGGER.warning("Anglican calendar lookup failed: %s", exc)
        return None, None, None, None, None, ""


# ---------------------------------------------------------------------------
# Image composition (synchronous — runs in executor)
# ---------------------------------------------------------------------------

def _compose_image(
    size: tuple[int, int],
    parsed,
    season: str,
    week: str,
    description: str,
    saint_image_bytes: bytes | None,
    font_path: str | None,
    name_font_path: str | None,
    calendar_tag: str = "",
) -> bytes:
    from ..saint_name import render_saints_day_image
    return render_saints_day_image(
        size=size,
        parsed=parsed,
        season=season,
        week=week,
        description=description,
        saint_image_bytes=saint_image_bytes,
        font_path=font_path,
        name_font_path=name_font_path,
        calendar_tag=calendar_tag,
    )


# ---------------------------------------------------------------------------
# Calendar tag helpers
# ---------------------------------------------------------------------------

_ANG_TYPE_LABELS: dict[str, str] = {
    "principal feast":    "Principal Feast",
    "principal holy day": "Principal Holy Day",
    "festival":           "Festival",
    "lesser festival":    "Lesser Festival",
    "commemoration":      "Commemoration",
    "sunday":             "Sunday",
}
_CAT_RANK_LABELS: dict[str, str] = {
    "solemnity":   "Solemnity",
    "feast":       "Feast",
    "memorial":    "Memorial",
    "opt_memorial": "Opt. Memorial",
}
_ANG_RANK_NUM: dict[str, int] = {
    "principal feast": 9, "sunday": 8, "principal holy day": 7,
    "festival": 7, "lesser festival": 6, "commemoration": 5,
}
_CAT_RANK_NUM: dict[str, int] = {
    "solemnity": 9, "feast": 7, "memorial": 6, "opt_memorial": 5,
}


def _compute_calendar_tag(
    result: "CombinedResult",
    cat_feasts: list,
    ang_type: str,
) -> str:
    """Compute the bottom-right corner tag text for the display.

    Flagged Anglican wins  → "Anglican Festival"
    Flagged Catholic wins  → "Catholic Solemnity"
    Shared / unflagged     → rank label only (no tradition word); Catholic
                             preferred when ranks are equivalent.
    No feast               → ""
    """
    if result.source == "none" or not result.display_name:
        return ""

    # Find the best Catholic rank for this date:
    # For a flagged Catholic win, match the winning display_name to its rank.
    # For shared / Anglican wins, use the highest-ranked Catholic option.
    cat_rank_str = ""
    if cat_feasts:
        opts: list[tuple[str, str]] = []   # (name, rank)
        for f in cat_feasts:
            if "/" in f.name:
                for seg in f.name.split("/"):
                    seg = seg.strip()
                    if seg:
                        opts.append((seg, f.rank))
            else:
                opts.append((f.name, f.rank))

        if result.flag and result.flag_source == "catholic":
            # Match winning name to its specific rank
            cat_rank_str = next(
                (rank for name, rank in opts if name == result.display_name),
                cat_feasts[0].rank,
            )
        elif opts:
            # Shared or Anglican win: compare against highest Catholic rank
            cat_rank_str = max(opts, key=lambda x: _CAT_RANK_NUM.get(x[1].lower(), 4))[1]

    ang_key = ang_type.lower().strip()
    cat_key = cat_rank_str.lower().strip()

    if result.flag:
        if result.flag_source == "anglican":
            label = _ANG_TYPE_LABELS.get(ang_key, ang_type.title())
            return f"Anglican {label}".strip()
        if result.flag_source == "catholic":
            label = _CAT_RANK_LABELS.get(cat_key, cat_rank_str.title())
            return f"Catholic {label}".strip()
        return ""

    # Shared / unflagged: show rank of higher tradition; prefer Catholic if equal
    a_num = _ANG_RANK_NUM.get(ang_key, 4)
    c_num = _CAT_RANK_NUM.get(cat_key, 4)
    if c_num >= a_num and cat_rank_str:
        return _CAT_RANK_LABELS.get(cat_key, cat_rank_str.title())
    ang_label = _ANG_TYPE_LABELS.get(ang_key, "")
    return ang_label


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _get_season_description(season: str | None) -> str:
    if not season:
        return ""
    for key in SEASON_DESCRIPTIONS:
        if key.lower() in season.lower():
            return SEASON_DESCRIPTIONS[key]
    return ""


def _format_week(week: str) -> str:
    if not week:
        return week
    parts = week.strip().split()
    if len(parts) == 2:
        season_name, number = parts[0], parts[1]
        ordinal = ORDINALS.get(number, number)
        return f"{ordinal} Week of {season_name}"
    return week


def _parse_size(size_str: str) -> tuple[int, int]:
    try:
        w, h = size_str.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 64, 64
