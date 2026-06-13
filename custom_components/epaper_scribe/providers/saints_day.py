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
from ..dither import async_write_to_file
from . import ContentProvider, SensorDescription
from .liturgical_calendar import (
    AnglicanDay,
    CombinedResult,
    fetch_catholic_year,
    get_catholic_feasts,
    get_catholic_season,
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
    "Paschal Triduum": (
        "The Paschal Triduum is the heart of the liturgical year — three days treated as one great vigil. "
        "It begins at the Mass of the Lord's Supper on Holy Thursday evening, continues through "
        "the Passion on Good Friday and the silence of Holy Saturday, "
        "and reaches its climax at the Easter Vigil."
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
    "Ordinary": (
        "Ordinary Time is the season of daily faithfulness — the Church living out "
        "in the world what it has celebrated at the font and table. "
        "Green vestments mark a season of growth: hearing the Word, practising charity, "
        "and being formed week by week into the Body of Christ."
    ),
}

def _martyrology_death_year(martyrology: tuple) -> int | None:
    """Return the earliest numeric death year from a martyrology tuple, or None.

    Only integer years and ISO-date strings are considered — dict forms
    (century, or, between) are too vague to be useful as a disambiguation signal.
    """
    result: int | None = None
    for item in martyrology:
        dod = item.date_of_death
        if isinstance(dod, int):
            if result is None or dod < result:
                result = dod
        elif isinstance(dod, str):
            try:
                y = int(dod[:4])
                if result is None or y < result:
                    result = y
            except (ValueError, TypeError):
                pass
    return result


def _compose_martyrology_description(martyrology: tuple) -> str:
    """Build a brief fallback prose description from martyrology items.

    Used when Wikipedia search returns nothing.  Produces a short sentence
    drawn from structured martyrology data: titles, birth/death/beatification/
    canonization dates, and canonization level (Saint vs. Blessed).
    """
    if not martyrology:
        return ""

    _LABELS: dict[str, str] = {
        "MARTYR": "martyr",
        "BISHOP": "bishop",
        "PRIEST": "priest",
        "DEACON": "deacon",
        "DOCTOR_OF_THE_CHURCH": "Doctor of the Church",
        "APOSTLE": "apostle",
        "VIRGIN": "virgin",
        "ABBOT": "abbot",
        "ABBESS": "abbess",
        "MONK": "monk",
        "NUN": "nun",
        "RELIGIOUS": "religious",
        "POPE": "pope",
        "CONFESSOR": "confessor",
        "WIDOW": "widow",
        "MISSIONARY": "missionary",
        "HERMIT": "hermit",
        "KING": "king",
        "QUEEN": "queen",
        "EVANGELIST": "evangelist",
        "ARCHANGEL": "archangel",
        "EMPRESS": "empress",
        "PROPHET": "prophet",
        "PILGRIM": "pilgrim",
        "THE_FIRST_MARTYR": "first martyr",
        "SPOUSE_OF_THE_BLESSED_VIRGIN_MARY": "spouse of the Blessed Virgin Mary",
        "PARENTS_OF_THE_BLESSED_VIRGIN_MARY": "parents of the Blessed Virgin Mary",
        "QUEEN_OF_POLAND": "Queen of Poland",
    }
    _PLURALS: dict[str, str] = {
        "martyr": "martyrs", "bishop": "bishops", "priest": "priests",
        "deacon": "deacons", "Doctor of the Church": "Doctors of the Church",
        "apostle": "apostles", "virgin": "virgins", "abbot": "abbots",
        "abbess": "abbesses", "monk": "monks", "nun": "nuns",
        "religious": "religious", "pope": "popes", "confessor": "confessors",
        "widow": "widows", "missionary": "missionaries", "hermit": "hermits",
        "king": "kings", "queen": "queens", "evangelist": "evangelists",
        "archangel": "archangels", "empress": "empresses",
        "prophet": "prophets", "pilgrim": "pilgrims",
        "first martyr": "first martyrs",
    }

    def _date_display(value) -> str:
        """Convert a martyrology date field (int, str, or dict) to a display string."""
        if value is None:
            return ""
        if isinstance(value, int):
            return f"around {value}" if value < 1000 else str(value)
        if isinstance(value, str):
            try:
                y = int(value[:4])
                return f"around {y}" if y < 1000 else str(y)
            except (ValueError, TypeError):
                return ""
        if isinstance(value, dict):
            if "century" in value:
                c = int(value["century"])
                sfx = "th" if 11 <= c % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(c % 10, "th")
                return f"the {c}{sfx} century"
            if "or" in value:
                years = sorted(y for y in value["or"] if isinstance(y, int))
                if years:
                    return f"around {years[0]}" if years[0] < 1000 else str(years[0])
            if "between" in value:
                vals = value["between"]
                years = []
                for v in vals:
                    if isinstance(v, int):
                        years.append(v)
                    elif isinstance(v, str):
                        try:
                            years.append(int(v[:4]))
                        except (ValueError, TypeError):
                            pass
                if len(years) >= 2:
                    return f"between {min(years)} and {max(years)}"
                if years:
                    return f"around {years[0]}" if years[0] < 1000 else str(years[0])
        return ""

    def _earliest_date_display(items, attr: str) -> str:
        """Return the display string for the earliest numeric value of *attr* across items.

        Dict-form dates (century, or, between) are used as fallback only if no
        numeric year is found.
        """
        numeric: list[tuple[int, object]] = []
        dict_fallback = ""
        for item in items:
            val = getattr(item, attr, None)
            if val is None:
                continue
            if isinstance(val, int):
                numeric.append((val, val))
            elif isinstance(val, str):
                try:
                    numeric.append((int(val[:4]), val))
                except (ValueError, TypeError):
                    pass
            elif isinstance(val, dict):
                if not dict_fallback:
                    dict_fallback = _date_display(val)
        if numeric:
            numeric.sort()
            return _date_display(numeric[0][1])
        return dict_fallback

    # ── Plurality ────────────────────────────────────────────────────────────
    group_count = next((item.count for item in martyrology if item.count is not None), None)
    plural = len(martyrology) > 1 or (
        group_count is not None and group_count not in (1, "1")
    )

    # ── Titles ───────────────────────────────────────────────────────────────
    seen: set[str] = set()
    title_labels: list[str] = []
    for item in martyrology:
        for t in (item.titles or []):
            lbl = _LABELS.get(t, t.replace("_", " ").lower())
            if lbl not in seen:
                seen.add(lbl)
                title_labels.append(lbl)
    if plural:
        title_labels = [_PLURALS.get(t, t) for t in title_labels]

    # ── Dates ────────────────────────────────────────────────────────────────
    dob_str   = _earliest_date_display(martyrology, "date_of_birth")
    dod_str   = _earliest_date_display(martyrology, "date_of_death")
    beat_str  = _earliest_date_display(martyrology, "date_of_beatification")
    canon_str = _earliest_date_display(martyrology, "date_of_canonization")

    # ── Canonization level ───────────────────────────────────────────────────
    levels = {item.canonization_level for item in martyrology if item.canonization_level}
    is_blessed_only = "BLESSED" in levels and "SAINT" not in levels
    hide_level = all(getattr(item, "hide_canonization_level", False) for item in martyrology)
    blessed_prefix = "Blessed " if is_blessed_only and not hide_level else ""

    # ── Fact clauses (born …, died …, beatified …, canonized …) ─────────────
    facts: list[str] = []
    if dob_str:
        facts.append(f"born {dob_str}")
    if dod_str:
        facts.append(f"died {dod_str}")
    if beat_str:
        facts.append(f"beatified {beat_str}")
    if canon_str:
        facts.append(f"canonized {canon_str}")
    facts_str = ", ".join(facts)

    # ── Title phrase ─────────────────────────────────────────────────────────
    if len(title_labels) == 0:
        title_phrase = ""
    elif len(title_labels) == 1:
        title_phrase = title_labels[0]
    elif len(title_labels) == 2:
        title_phrase = f"{title_labels[0]} and {title_labels[1]}"
    else:
        title_phrase = ", ".join(title_labels[:-1]) + ", and " + title_labels[-1]

    # ── Compose ──────────────────────────────────────────────────────────────
    martyr_labels = {"martyr", "martyrs", "first martyr", "first martyrs"}
    is_martyr = bool({t.lower() for t in title_labels} & martyr_labels)

    if is_martyr:
        non_martyr = [t for t in title_labels if t.lower() not in martyr_labels]
        role = "martyrs" if plural else "martyr"
        if non_martyr:
            role += " and " + " and ".join(non_martyr)
        prefix = blessed_prefix or ("Christian " if plural else "")
        sentence = f"{prefix}{role}"
        if facts_str:
            sentence += f", {facts_str}"
        return (sentence + ".").capitalize()

    if title_phrase:
        phrase = blessed_prefix + title_phrase[0].lower() + title_phrase[1:]
        sentence = phrase[0].upper() + phrase[1:]
        if facts_str:
            return f"{sentence}, {facts_str}."
        return f"{sentence}."

    if facts_str:
        return facts_str[0].upper() + facts_str[1:] + "."

    return "Commemorated in the Roman Catholic calendar."


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

    async def async_initialize(self) -> None:
        size = _parse_size(self.config.get(CONF_DEFAULT_SIZE, "64x64"))
        await async_write_to_file(
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
        elif calendar_type == CALENDAR_CATHOLIC:
            data = await self._render_catholic(today, size, palette)
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
            get_combined_result, today, ang_day, self._year_cache_ang
        )

        saint_name = ""
        saint_role = ""
        description = ""
        image_bytes: bytes | None = None

        # Fetch Catholic feasts early so we can extract the death-year hint
        # for Wikipedia disambiguation resolution before the Wikipedia fetch.
        cat_feasts_today = await self.hass.async_add_executor_job(get_catholic_feasts, today)

        parsed = None
        if result.source != "none" and result.display_name:
            from ..saint_name import parse_saint_name
            parsed = parse_saint_name(result.display_name)
            saint_role_parts = [s.descriptor for s in parsed.segments if s.descriptor]
            saint_name = " · ".join(s.name for s in parsed.segments) if parsed.segments else result.display_name
            saint_role = " · ".join(saint_role_parts)

            names = [s.name for s in parsed.segments] if parsed.segments else [result.display_name]
            descs = [s.descriptor for s in parsed.segments] if parsed.segments else []

            # Derive death-year hint from the matching Catholic feast (if the
            # winner is Catholic-sourced).  Anglican-sourced saints rely on
            # wiki_url (step 0) so hint_year is less important for them.
            hint_year: int | None = None
            if result.source == "catholic" and cat_feasts_today:
                cat_feast_hint = next(
                    (f for f in cat_feasts_today if f.name == result.display_name),
                    cat_feasts_today[0],
                )
                hint_year = _martyrology_death_year(cat_feast_hint.martyrology)

            description, image_url = await self._fetch_wikipedia(
                names, result.wiki_url, descs,
                hint_year=hint_year,
                hint_mmdd=today.strftime("%m-%d"),
            )
            if image_url:
                image_bytes = await self._fetch_image(image_url)

        font_path = self.config.get(CONF_FONT_PATH)
        name_font_path = self.config.get(CONF_NAME_FONT_PATH)
        season_desc = _get_season_description(result.season)
        ang_type = result.anglican.type_ if result.anglican else ""

        # Martyrology fallback for Catholic-sourced saints when Wikipedia fails.
        # Find the matching CatholicFeast by name (fall back to first if no exact match).
        if not description and result.source == "catholic" and result.display_name and cat_feasts_today:
            cat_feast = next(
                (f for f in cat_feasts_today if f.name == result.display_name),
                cat_feasts_today[0],
            )
            if cat_feast.martyrology:
                description = _compose_martyrology_description(cat_feast.martyrology)

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
            palette,
        )

        filename = f"saints_day_artwork_{size[1]}.png"
        await async_write_to_file(
            self.hass, filename, composed, size, (180, 160, 140)
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
        """Fetch the full year of Anglican data and warm the Catholic year cache."""
        ang_data: dict[str, AnglicanDay] = await self.hass.async_add_executor_job(
            _fetch_anglican_year, year
        )
        # Warm the module-level Catholic year cache so the first render is fast.
        await self.hass.async_add_executor_job(fetch_catholic_year, year)
        self._year_cache_year = year
        self._year_cache_ang = ang_data

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
            palette,
        )

        filename = f"saints_day_artwork_{size[1]}.png"
        await async_write_to_file(
            self.hass, filename, composed, size, (180, 160, 140)
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
    # Catholic-only mode
    # ------------------------------------------------------------------

    async def _render_catholic(
        self, today: date, size: tuple[int, int], palette: str
    ) -> dict[str, Any]:
        """Render Roman Catholic calendar without any Anglican data."""
        cat_feasts = await self.hass.async_add_executor_job(get_catholic_feasts, today)

        saint_name = ""
        saint_role = ""
        description = ""
        image_bytes: bytes | None = None
        calendar_tag = ""
        parsed = None

        if cat_feasts:
            # romcal returns entries highest-precedence first; take the primary
            primary = cat_feasts[0]
            from ..saint_name import parse_saint_name
            parsed = parse_saint_name(primary.name)
            saint_role_parts = [s.descriptor for s in parsed.segments if s.descriptor]
            saint_name = (
                " · ".join(s.name for s in parsed.segments)
                if parsed.segments else primary.name
            )
            saint_role = " · ".join(saint_role_parts)

            names = [s.name for s in parsed.segments] if parsed.segments else [primary.name]
            descs = [s.descriptor for s in parsed.segments] if parsed.segments else []
            description, image_url = await self._fetch_wikipedia(
                names, "", descs,
                hint_year=_martyrology_death_year(primary.martyrology),
                hint_mmdd=today.strftime("%m-%d"),
            )
            if image_url:
                image_bytes = await self._fetch_image(image_url)

            # Martyrology fallback: compose a brief prose description from
            # structured data when Wikipedia search returns nothing.
            if not description and primary.martyrology:
                description = _compose_martyrology_description(primary.martyrology)

            rank_label = _CAT_RANK_LABELS.get(primary.rank.lower(), primary.rank.title())
            calendar_tag = f"Catholic {rank_label}"

        season = await self.hass.async_add_executor_job(get_catholic_season, today)
        season_desc = _get_season_description(season)

        font_path = self.config.get(CONF_FONT_PATH)
        name_font_path = self.config.get(CONF_NAME_FONT_PATH)
        composed = await self.hass.async_add_executor_job(
            _compose_image,
            size,
            parsed,
            season,
            "",   # week — not available from romcal
            description if saint_name else season_desc,
            image_bytes,
            font_path,
            name_font_path,
            calendar_tag,
            palette,
        )

        filename = f"saints_day_artwork_{size[1]}.png"
        await async_write_to_file(
            self.hass, filename, composed, size, (180, 160, 140)
        )
        self._image_bytes = composed
        self._image_last_updated = datetime.now()

        return {
            "saint_name": saint_name,
            "saint_role": saint_role,
            "season": season,
            "week": "",
            "description": description,
            "season_description": season_desc,
            "has_saint": bool(saint_name),
            "calendar_source": "catholic",
            "calendar_flag": False,
        }

    # ------------------------------------------------------------------
    # Shared fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_wikipedia_one(self, search_term: str) -> tuple[str, str]:
        """Fetch the Wikipedia REST summary for *search_term*.

        Thin wrapper around _fetch_wikipedia_one_full; hides the disambiguation
        title from callers that don't need it.  Returns ("", "") on
        disambiguation, non-200 status, or exception.
        """
        ex, img, _ = await self._fetch_wikipedia_one_full(search_term)
        return ex, img

    async def _fetch_wikipedia_one_full(
        self, search_term: str
    ) -> tuple[str, str, str]:
        """Fetch Wikipedia REST summary, surfacing disambiguation page titles.

        Returns (extract, image_url, dis_title) where dis_title is the
        canonical Wikipedia page title when the result is a disambiguation page,
        and "" otherwise.  extract and image_url are "" on disambiguation.
        """
        try:
            session = async_get_clientsession(self.hass)
            headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
            url = WIKIPEDIA_API + quote(search_term)
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return "", "", ""
                data = await resp.json()
            if data.get("type") == "disambiguation":
                # Return the canonical title so the caller can resolve it.
                return "", "", data.get("title", search_term)
            return (
                data.get("extract", ""),
                data.get("thumbnail", {}).get("source", ""),
                "",
            )
        except Exception as exc:
            _LOGGER.warning("Wikipedia fetch failed for %r: %s", search_term, exc)
            return "", "", ""

    async def _resolve_from_disambiguation(
        self,
        dis_title: str,
        first_name: str,
        hint_year: int | None,
        hint_mmdd: str,
    ) -> tuple[str, str]:
        """Identify the correct saint article from a Wikipedia disambiguation page.

        Strategy
        ────────
        1. Fetch the disambiguation page wikitext and parse section headers.
           Only collect article links from sections whose header contains
           "people", "saints", "religious", etc.  If no such sections exist,
           fall back to every link whose title contains *first_name*.

        2. For each candidate article, fetch its wikitext and inspect the
           infobox fields ``feast_day`` and ``death_date`` directly:
               +20  infobox death_date contains the known death year
               +15  infobox feast_day contains today's feast date

        3. Also score the REST summary text as a lower-confidence fallback:
               +5   article text mentions the death year
               +3   article text mentions today's feast date

        4. Return the highest-scoring candidate that has score > 0.
           Returns ("", "") when no candidate passes the threshold.

        This deliberately requires a positive signal — it never guesses.
        Multi-line infobox templates (e.g. ``{{indented plainlist}}``) are
        handled by scanning the following lines after the field declaration.
        """
        import calendar as _cal
        import re as _re

        session = async_get_clientsession(self.hass)
        headers = {"User-Agent": "HomeAssistantDisplay/1.0 epaper-scribe"}
        fn_lower = first_name.lower()
        year_str = str(hint_year) if hint_year is not None else ""

        # ── Build feast-date match patterns ───────────────────────────────────
        feast_patterns: list[str] = []
        if hint_mmdd:
            try:
                month_num = int(hint_mmdd.split("-")[0])
                day_num   = int(hint_mmdd.split("-")[1])
                month_name = _cal.month_name[month_num].lower()
                feast_patterns = [
                    f"{month_name} {day_num}",   # "may 12"
                    f"{day_num} {month_name}",    # "12 may"
                ]
            except (ValueError, IndexError):
                pass

        # ── 1. Fetch disambiguation page wikitext ─────────────────────────────
        try:
            url = (
                WIKIPEDIA_MW_API
                + "?action=query&prop=revisions&rvprop=content&rvslots=main"
                + "&format=json&redirects=1&titles=" + quote(dis_title)
            )
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return "", ""
                data = await resp.json()
            pages = data.get("query", {}).get("pages", {})
            dis_wikitext = ""
            for page in pages.values():
                rev = (page.get("revisions") or [{}])[0]
                dis_wikitext = (
                    rev.get("slots", {}).get("main", {}).get("*", "")
                    or rev.get("*", "")
                )
                break
        except Exception as exc:
            _LOGGER.debug("Disambiguation wikitext fetch failed for %r: %s", dis_title, exc)
            return "", ""

        # ── 2. Parse wikitext — section-filtered candidate links ──────────────
        PERSON_KEYWORDS = {
            "people", "person", "persons", "saints", "saint",
            "religious", "clergy", "christian", "christians",
            "martyr", "martyrs", "biography", "biographies",
        }

        in_person_section = False
        has_person_sections = False
        person_links: list[str] = []   # links from person-type sections
        all_name_links: list[str] = [] # all links matching first_name

        for line in dis_wikitext.split("\n"):
            hdr_m = _re.match(r'^={2,}\s*(.+?)\s*={2,}\s*$', line)
            if hdr_m:
                words = set(hdr_m.group(1).lower().split())
                in_person_section = bool(words & PERSON_KEYWORDS)
                if in_person_section:
                    has_person_sections = True
                continue
            for lm in _re.finditer(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]', line):
                title = lm.group(1).strip()
                if fn_lower in title.lower():
                    all_name_links.append(title)
                    if in_person_section:
                        person_links.append(title)

        # Prefer section-filtered list; fall back to all-name list when no
        # person sections were found or (safety) when section list is empty.
        raw_candidates = (
            person_links
            if has_person_sections and person_links
            else all_name_links
        )
        # Deduplicate while preserving order
        seen_c: set[str] = set()
        candidates: list[str] = []
        for t in raw_candidates:
            if t not in seen_c:
                seen_c.add(t)
                candidates.append(t)

        if not candidates:
            _LOGGER.debug("Disambiguation %r: no candidates matching %r", dis_title, first_name)
            return "", ""

        _LOGGER.debug(
            "Disambiguation %r: %d candidate(s) (person_sections=%s): %s",
            dis_title, len(candidates), has_person_sections, candidates,
        )

        # ── 3. Score each candidate ───────────────────────────────────────────
        best_ex = ""
        best_img = ""
        best_score = -1

        for title in candidates:
            infobox_score = 0

            # 3a. Fetch candidate wikitext for infobox field scoring
            try:
                url = (
                    WIKIPEDIA_MW_API
                    + "?action=query&prop=revisions&rvprop=content&rvslots=main"
                    + "&format=json&redirects=1&titles=" + quote(title)
                )
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        art_data = await resp.json()
                        art_pages = art_data.get("query", {}).get("pages", {})
                        art_wikitext = ""
                        for art_page in art_pages.values():
                            rev = (art_page.get("revisions") or [{}])[0]
                            art_wikitext = (
                                rev.get("slots", {}).get("main", {}).get("*", "")
                                or rev.get("*", "")
                            )
                            break
                        if art_wikitext:
                            death_val = _extract_infobox_field(art_wikitext, "death_date")
                            feast_val = _extract_infobox_field(art_wikitext, "feast_day")
                            if year_str and death_val and year_str in death_val:
                                infobox_score += 20
                            if feast_patterns and feast_val:
                                fv_lower = feast_val.lower()
                                if any(p in fv_lower for p in feast_patterns):
                                    infobox_score += 15
            except Exception as exc:
                _LOGGER.debug("Wikitext fetch failed for candidate %r: %s", title, exc)

            # 3b. Fetch REST summary for extract text + image
            ex, img, dis = await self._fetch_wikipedia_one_full(title)
            if not ex or dis:
                continue   # skip failed fetches and nested disambiguations

            text_score = 0
            text_lower = ex.lower()
            if year_str and year_str in ex:
                text_score += 5
            if feast_patterns and any(p in text_lower for p in feast_patterns):
                text_score += 3

            score = infobox_score + text_score
            _LOGGER.debug(
                "Disambiguation candidate %r: infobox=%d text=%d total=%d",
                title, infobox_score, text_score, score,
            )

            if score > best_score:
                best_score = score
                best_ex = ex
                best_img = img

        if best_score > 0:
            _LOGGER.debug("Disambiguation resolved %r → score=%d", dis_title, best_score)
            return best_ex, best_img

        _LOGGER.debug("Disambiguation %r: no candidate had a positive score", dis_title)
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
        hint_year: int | None = None,
        hint_mmdd: str = "",
    ) -> tuple[str, str]:
        """Fetch a Wikipedia description for one or more saints.

        *names* may include compound entries like "Philip and James"; these are
        expanded into individual people.  *descriptors* are the corresponding
        role words per name segment ("Apostles", "Monk", …).

        *hint_year* (death year from martyrology) and *hint_mmdd* ("MM-DD"
        today's feast date) are used to resolve disambiguation pages: when all
        direct searches fail because a title is a disambiguation page, we scan
        that page's linked articles and score them against the hints.

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
          2b. "Saint {name} the {descriptor}"
          2c. "{name} the {descriptor}"
          2d. "Saint {name}"
          2e. "{name}"
          First sentences are combined; first image is used.

          If every candidate returns ("","") and at least one was a
          disambiguation page, _resolve_from_disambiguation is called with the
          death-year and feast-date hints before moving on.

        For a *single* name with no expansion:
          Same individual cascade (2a–2e).

        The authoritative *wiki_url* (from the Anglican calendar) is tried
        before any search, but only accepted if it covers all individuals.
        """
        import re as _re

        # ── Title feasts of the Lord / Christ / Mary ───────────────────────
        # Handled before compound expansion: some titles contain "and"
        # ("...Body and Blood of Christ") which the expansion would wrongly
        # split into two people.  Skipped when an authoritative wiki_url is
        # available (the Anglican calendar supplies a direct article link).
        if not wiki_url and len(names) == 1:
            title_terms = _title_feast_search_terms(names[0])
            if title_terms:
                for q in title_terms:
                    ex, img = await self._fetch_wikipedia_one(q)
                    if ex:
                        first = ex.split(". ")[0].strip()
                        if not first.endswith("."):
                            first += "."
                        return first, img
                return "", ""

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
            first_dis_title = ""   # canonical title of first disambiguation hit
            for q in candidates:
                ex, im, dis_title = await self._fetch_wikipedia_one_full(q)
                if ex:
                    successful_q = q
                    break
                if dis_title and not first_dis_title:
                    first_dis_title = dis_title

            # Disambiguation fallback: all direct queries failed; if any hit a
            # disambiguation page, try to resolve using death year / feast date.
            if not ex and first_dis_title and (hint_year is not None or hint_mmdd):
                ex, im = await self._resolve_from_disambiguation(
                    first_dis_title, name.split()[0], hint_year, hint_mmdd
                )
                if ex:
                    successful_q = first_dis_title

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
    palette: str | None = None,
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
        palette=palette,
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
        opts: list[tuple[str, str]] = [(f.name, f.rank) for f in cat_feasts]

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
# Title-feast normalization (feasts of the Lord / Christ / Mary)
# ---------------------------------------------------------------------------
#
# Devotional / festal titles such as "The Most Sacred Heart of Jesus" or
# "The Immaculate Heart of the Blessed Virgin Mary" are NOT personal saints:
# they never take a "Saint " prefix, and their ornate romcal names do not match
# a Wikipedia article verbatim (the REST summary endpoint errors on them).
# Stripping "The "/"Most " and reducing "the Blessed Virgin Mary" → "Mary"
# yields titles that resolve directly (e.g. "Sacred Heart of Jesus" → Sacred
# Heart; "Immaculate Heart of Mary" → Immaculate Heart of Mary).
#
# Detection is by specific feast-noun keywords rather than a blanket "of Jesus"
# test, so personal saints like "Teresa of Jesus" are never misclassified.

_TITLE_FEAST_KEYWORDS: tuple[str, ...] = (
    "sacred heart", "immaculate heart", "holy trinity", "holy cross",
    "holy name", "holy face", "holy family", "body and blood",
    "precious blood", "transfiguration", "exaltation", "presentation of",
    "annunciation", "assumption", "visitation", "immaculate conception",
    "queenship", "nativity of", "dedication of", "baptism of the lord",
    "divine mercy", "christ the king", "king of the universe",
)

# Normalized (lowercased) title → explicit Wikipedia article when the
# stripped form does not itself resolve.
_TITLE_FEAST_ALIASES: dict[str, str] = {
    "holy body and blood of christ": "Corpus Christi (feast)",
    "body and blood of christ": "Corpus Christi (feast)",
}


def _normalize_title_feast(name: str) -> str:
    """Reduce an ornate title-feast name to its plain Wikipedia-searchable form."""
    import re as _re

    n = name.strip()
    n = _re.sub(r'^[Tt]he\s+', '', n)
    n = _re.sub(r'^Most\s+(?=Holy\b)', '', n)   # "Most Holy X" → "Holy X"
    n = _re.sub(r'^Most\s+', '', n)             # "Most Sacred X" → "Sacred X"
    n = _re.sub(
        r'(?:the\s+)?Blessed\s+Virgin\s+Mary', 'Mary', n, flags=_re.IGNORECASE
    )
    return n.strip()


def _title_feast_search_terms(name: str) -> list[str]:
    """Return ordered Wikipedia search candidates if *name* is a title feast.

    Returns [] for ordinary personal-saint names so the caller falls through
    to the regular "Saint X" cascade.
    """
    low = name.lower()
    if not (low.startswith("our lady") or any(k in low for k in _TITLE_FEAST_KEYWORDS)):
        return []
    norm = _normalize_title_feast(name)
    terms: list[str] = []
    alias = _TITLE_FEAST_ALIASES.get(norm.lower())
    if alias:
        terms.append(alias)
    if norm and norm not in terms:
        terms.append(norm)
    if name not in terms:
        terms.append(name)
    return terms


# ---------------------------------------------------------------------------
# Wikipedia wikitext helpers
# ---------------------------------------------------------------------------

def _extract_infobox_field(wikitext: str, field_name: str) -> str:
    """Extract a named field's raw value from a Wikipedia infobox.

    Handles both single-line values and multi-line values produced by
    templates such as ``{{indented plainlist}}``.  Returns a string
    containing the field declaration line plus up to four following lines,
    which is sufficient for the date patterns we check.

    Example inputs handled:
      ``| death_date = 12 May 303 or 304``          → one-line
      ``| feast_day = {{indented plainlist           → multi-line
           | 23 April
           | 3 November (Eastern)
        }}``
    """
    import re as _re

    pattern = _re.compile(
        r'^\|\s*' + _re.escape(field_name) + r'\s*=',
        _re.IGNORECASE | _re.MULTILINE,
    )
    m = pattern.search(wikitext)
    if not m:
        return ""
    # Return the field declaration line plus up to 4 subsequent lines so
    # that multi-line template bodies are included in the search window.
    start = wikitext.rfind("\n", 0, m.start()) + 1   # start of that line
    segment = wikitext[start:]
    lines = segment.split("\n", 5)[:5]               # field line + 4 more
    return "\n".join(lines)


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
