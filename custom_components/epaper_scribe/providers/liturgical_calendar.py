"""Unified liturgical calendar provider for E-Paper Scribe.

Covers three modes:
  - "combined"  — Anglican + Catholic with cross-date rules (default)
  - "anglican"  — Church of England calendar only
  - "catholic"  — Roman Catholic General Calendar only

Catholic data is sourced from python-romcal, a pure-Python port of
romcal/romcal 3.0.0-dev.125 (General Roman Calendar, English locale).

Anglican data is sourced from the `liturgical-calendar` Python package.

Combined-mode selection is deterministic for a given date: the same date
always produces the same result within a year (hash-based) and cross-date
edge cases are pre-computed once per calendar year.

Catholic rank values (highest → lowest):
  SOLEMNITY > FEAST > MEMORIAL > OPT_MEMORIAL
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from romcal import Romcal
from romcal.bundles import GeneralRoman_En

# romcal 3.x rank strings → CatholicFeast rank
_RANK_MAP: dict[str, str] = {
    "SOLEMNITY": "SOLEMNITY",
    "FEAST": "FEAST",
    "MEMORIAL": "MEMORIAL",
    "OPTIONAL_MEMORIAL": "OPT_MEMORIAL",
}

# romcal IDs for Easter Octave weekdays (Monday–Saturday)
_EASTER_OCTAVE_WEEKDAY_IDS: frozenset[str] = frozenset({
    "easter_monday",
    "easter_tuesday",
    "easter_wednesday",
    "easter_thursday",
    "easter_friday",
    "easter_saturday",
})

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatholicFeast:
    """A single Catholic liturgical celebration on a date."""

    name: str
    rank: str          # "SOLEMNITY" | "FEAST" | "MEMORIAL" | "OPT_MEMORIAL"
    from_calendar: str = ""  # romcal fromCalendarId: "ProperOfTime" | "me" | ...
    feast_id: str = ""       # romcal day id, e.g. "sacred_heart_of_jesus"

    @property
    def rank_value(self) -> int:
        return {"SOLEMNITY": 4, "FEAST": 3, "MEMORIAL": 2, "OPT_MEMORIAL": 1}.get(
            self.rank, 0
        )

    @property
    def is_proper_of_time(self) -> bool:
        """True for temporal cycle entries (Easter Octave, Sacred Heart, etc.)."""
        return self.from_calendar == "ProperOfTime"


@dataclass
class AnglicanDay:
    name: str        # raw package name, may include "(transferred)"
    week: str
    season: str
    type_: str       # "Principal Feast", "Sunday", "Holy Day", etc.
    wiki_url: str = ""


@dataclass
class CombinedResult:
    # Classification
    category: str       # ANG_ONLY | CAT_ONLY | SHARED | SHARED_RANDOM | ALIAS |
                        # CONFLICT | HOLY_WEEK | NO_FEAST | CROSS_DATE
    # What to display
    display_name: str   # raw name string from the winning source
    source: str         # "anglican" | "catholic" | "none"
    # Flagging
    flag: bool          # True = show tradition indicator (◆)
    flag_source: str    # "anglican" | "catholic" | "" (which tradition wins)
    # Context
    season: str
    week: str
    wiki_url: str = ""
    # The Anglican day (always set for context even when Catholic wins)
    anglican: AnglicanDay | None = None


@dataclass
class CrossDateFlags:
    """Precomputed per-year cross-date rule outcomes.

    Each flag entry maps an MM-DD key to a display override instruction.
    """
    overrides: dict[str, str] = field(default_factory=dict)  # mmdd → rule label


# ---------------------------------------------------------------------------
# Module-level singletons (lazy-initialised)
# ---------------------------------------------------------------------------

_romcal = Romcal(localized_calendar=GeneralRoman_En)
_year_cache: dict[int, dict[str, list[CatholicFeast]]] = {}


# ---------------------------------------------------------------------------
# Catholic calendar generation
# ---------------------------------------------------------------------------


def _build_year_calendar(year: int) -> dict[str, list[CatholicFeast]]:
    """Generate the full Roman Catholic calendar for *year* via python-romcal."""
    raw = _romcal.generate_calendar(year)

    calendar: dict[str, list[CatholicFeast]] = {}
    for date_str, days in raw.items():
        feasts: list[CatholicFeast] = []
        for day in days:
            rank = _RANK_MAP.get(day.rank)
            if rank is None:
                continue  # skip WEEKDAY, SUNDAY, COMMEMORATION, etc.
            feasts.append(CatholicFeast(
                name=day.name,
                rank=rank,
                from_calendar=day.from_calendar_id,
                feast_id=day.id,
            ))
        if feasts:
            calendar[date_str] = feasts

    return calendar


def get_catholic_feasts(d: date) -> list[CatholicFeast]:
    """Return Catholic feast(s) for date *d*.

    Returns an empty list on ordinary weekdays with no celebration.
    Multiple entries are possible (e.g. two optional memorials on the same
    date). ProperOfTime entries are included; callers in combined mode
    should apply _filter_proper_of_time() before further processing.
    """
    year = d.year
    if year not in _year_cache:
        _year_cache[year] = _build_year_calendar(year)
    return _year_cache[year].get(d.isoformat(), [])


def fetch_catholic_year(year: int) -> dict[str, list[CatholicFeast]]:
    """Return all Catholic feasts for *year* as {iso_date: [CatholicFeast]}.

    Runs synchronously; intended to be called via async_add_executor_job.
    """
    if year not in _year_cache:
        _year_cache[year] = _build_year_calendar(year)
    return dict(_year_cache[year])


# ---------------------------------------------------------------------------
# ProperOfTime filtering helpers
# ---------------------------------------------------------------------------


def _is_sacred_heart(feast: CatholicFeast) -> bool:
    return (
        "sacred_heart" in feast.feast_id.lower()
        or "sacred heart" in feast.name.lower()
    )


def _is_easter_octave_weekday(feast: CatholicFeast) -> bool:
    return feast.feast_id in _EASTER_OCTAVE_WEEKDAY_IDS


def _filter_proper_of_time(
    feasts: Sequence[CatholicFeast],
    ang_real: bool,
    combined: bool,
) -> list[CatholicFeast]:
    """Filter ProperOfTime entries for combined-mode display.

    In Catholic-only mode all feasts pass through unchanged.

    In combined mode:
    - Sanctoral entries always pass through.
    - Sacred Heart passes through (treated as a saint's day).
    - Easter Octave weekdays pass through only when Anglican has no saint
      (i.e. ang_real is False); if Anglican has a saint, Anglican carries
      the day and the ProperOfTime entry is dropped.
    - All other ProperOfTime entries are dropped (Anglican carries temporal
      framework for combined mode).
    """
    if not combined:
        return list(feasts)

    filtered: list[CatholicFeast] = []
    for feast in feasts:
        if not feast.is_proper_of_time:
            filtered.append(feast)
        elif _is_sacred_heart(feast):
            filtered.append(feast)
        elif _is_easter_octave_weekday(feast):
            if not ang_real:
                filtered.append(feast)  # Anglican has nothing → Catholic carries
            # else: Anglican has a saint → Anglican carries the day; skip this entry
        # else: other ProperOfTime in combined mode → skip (Anglican temporal framework)
    return filtered


# ---------------------------------------------------------------------------
# Alias pairs: same celebration, different names across traditions
# ---------------------------------------------------------------------------

_ALIAS_PAIRS: list[tuple[str, str]] = [
    ("martyrs of japan",       "paul miki"),
    ("martyrs of uganda",      "charles lwanga"),
    ("anskar",                 "ansgar"),
    ("laurence",               "lawrence"),
    ("parents of the blessed", "joachim and anne"),  # Jul 26
]


def _is_alias(a: str, b: str) -> bool:
    al, bl = a.lower(), b.lower()
    for ap, cp in _ALIAS_PAIRS:
        if al.startswith(ap) and cp in bl:
            return True
        if bl.startswith(ap) and cp in al:
            return True
    return False


# ---------------------------------------------------------------------------
# Same-feast token matching
# ---------------------------------------------------------------------------

_STRIP: frozenset[str] = frozenset({
    "saint", "saints", "blessed", "venerable", "holy", "the", "of", "and",
    "our", "lady", "lord", "jesus", "christ", "bishop", "pope", "martyr",
    "martyrs", "confessor", "virgin", "abbot", "abbess", "monk", "priest",
    "deacon", "doctor", "apostle", "apostles", "missionary", "missionaries",
    "companions", "memorial", "feast", "solemnity", "patron", "europe",
    "religious", "hermit",
})


def _tokenise(s: str) -> frozenset[str]:
    return frozenset(
        t for t in re.sub(r"[^a-z\s]", "", s.lower()).split()
        if len(t) > 2 and t not in _STRIP
    )


def _same_feast(a: str, b: str) -> bool:
    if _is_alias(a, b):
        return True
    ta, tb = _tokenise(a), _tokenise(b)
    if not ta or not tb:
        return False
    if ta & tb:
        return True
    return ta <= tb or tb <= ta


# ---------------------------------------------------------------------------
# Hash-based stable random selection (same date → same result each render)
# ---------------------------------------------------------------------------

def _hash_mod(d: date, n: int) -> int:
    """Return a stable integer in [0, n) derived from the date string.

    Using the full ISO date (including year) means the same month/day can
    produce different results in different years, giving year-to-year variety
    while remaining stable within a given year.
    """
    digest = hashlib.md5(d.isoformat().encode()).hexdigest()
    return int(digest, 16) % n


def _hash_select(d: date) -> int:
    """Convenience wrapper: return 0 or 1 from the date string."""
    return _hash_mod(d, 2)


def _hash_pick(d: date, options: list[CatholicFeast]) -> CatholicFeast:
    """Hash-pick one option from *options* in a stable, year-varying way."""
    if len(options) == 1:
        return options[0]
    return options[_hash_mod(d, len(options))]


# ---------------------------------------------------------------------------
# Anglican day helpers
# ---------------------------------------------------------------------------

_WEEK_RE = re.compile(
    r"\b(Advent|Lent|Easter|Trinity|Christmas|Epiphany)\s+\d"
    r"|\d\s+(before|after)\s+(Advent|Lent|Christmas)"
    r"|^(Advent|Lent|Easter|Christmas|Ordinary)$"
    r"|Ordinary Time|^Trinity$|^Pentecost$",
    re.IGNORECASE,
)
_SUNDAY_RE = re.compile(r"Sunday$", re.IGNORECASE)


def _is_real_anglican(day: AnglicanDay) -> bool:
    name = day.name.strip()
    if not name:
        return False
    if _WEEK_RE.search(name):
        return False
    if _SUNDAY_RE.search(name) and day.type_ != "Principal Feast":
        return False
    return True


def _is_transferred(day: AnglicanDay) -> bool:
    return day.name.endswith("(transferred)")


def _base_name(day: AnglicanDay) -> str:
    """Strip '(transferred)' suffix for matching/display."""
    name = day.name
    if name.endswith("(transferred)"):
        name = name[: -len("(transferred)")].rstrip()
    return name


# ---------------------------------------------------------------------------
# Fixed dates for SHARED_RANDOM (both traditions celebrate the same reality;
# string selection is random but unflagged)
# ---------------------------------------------------------------------------

_SHARED_RANDOM_MMDD: frozenset[str] = frozenset({
    "03-19",  # Joseph of Nazareth / Husband of Mary
    "03-25",  # Annunciation
    "07-26",  # Parents of BVM / Joachim and Anne  (alias)
    "07-29",  # Mary, Martha and Lazarus / Saint Martha
    "08-06",  # Transfiguration
    "09-29",  # Michael and All Angels / Michael Gabriel Raphael
    "12-08",  # Conception of BVM / Immaculate Conception
})


# ---------------------------------------------------------------------------
# Cross-date flag precomputation
# ---------------------------------------------------------------------------

def _precompute_flags(
    year: int,
    ang: dict[str, AnglicanDay],
    cat: dict[str, list[CatholicFeast]],
) -> CrossDateFlags:
    flags = CrossDateFlags()

    def ang_name(mmdd: str) -> str:
        day = ang.get(f"{year}-{mmdd}")
        return _base_name(day).lower() if day else ""

    def cat_names(mmdd: str) -> list[str]:
        return [f.name.lower() for f in cat.get(f"{year}-{mmdd}", [])]

    # --- Ephrem rule (Jun 9 + Jun 10) ---
    if "columba" in ang_name("06-09") and "ephrem" in ang_name("06-10"):
        flags.overrides["06-09"] = "EPHREM_ANG"
        flags.overrides["06-10"] = "EPHREM_ANG"

    # --- Fisher+More / Goretti rule (Jun 22 + Jul 6) ---
    has_ang_alban_622 = "alban" in ang_name("06-22")
    has_cat_fisher_622 = any("fisher" in n for n in cat_names("06-22"))
    has_ang_fisher_706 = "fisher" in ang_name("07-06") or "more" in ang_name("07-06")
    if has_ang_alban_622 and has_cat_fisher_622 and has_ang_fisher_706:
        if _hash_select(date(year, 6, 22)) == 1:
            flags.overrides["07-06"] = "FISHER_CAT"

    # --- Augustine of Canterbury rule (May 26 + May 27) ---
    has_ang_aug_526 = "augustine" in ang_name("05-26")
    has_cat_aug_527 = any("augustine" in n for n in cat_names("05-27"))
    if has_ang_aug_526 and has_cat_aug_527:
        if _hash_select(date(year, 5, 26)) == 0:
            flags.overrides["05-27"] = "AUGUSTINE_ANG"

    # --- Philip and James rule (Anglican May 1 + Catholic May 3) ---
    a501 = ang.get(f"{year}-05-01")
    has_ang_pj_501 = (
        a501 and "philip" in _base_name(a501).lower()
        and "james" in _base_name(a501).lower()
    )
    has_cat_pj_503 = any("philip" in n for n in cat_names("05-03"))
    if has_ang_pj_501 and has_cat_pj_503:
        if _hash_select(date(year, 5, 1)) == 0:
            flags.overrides["05-03"] = "PHILIPJAMES_ANG"

    # --- Elizabeth of Hungary rule (Anglican Nov 17 + Catholic Nov 18) ---
    has_ang_eliz_1117 = "elizabeth" in ang_name("11-17")
    has_cat_eliz_1118 = any("elizabeth" in n for n in cat_names("11-18"))
    if has_ang_eliz_1117 and has_cat_eliz_1118:
        if _hash_select(date(year, 11, 17)) == 1:
            flags.overrides["11-18"] = "ELIZABETH_CAT"

    # --- Cyprian of Carthage rule (Anglican Sep 15 + Catholic Sep 16) ---
    has_ang_cyprian_915 = "cyprian" in ang_name("09-15")
    has_cat_cyprian_916 = any("cyprian" in n for n in cat_names("09-16"))
    if has_ang_cyprian_915 and has_cat_cyprian_916:
        if _hash_select(date(year, 9, 15)) == 0:
            flags.overrides["09-16"] = "CYPRIAN_ANG"

    # --- Baptism of Christ rule (Anglican Jan 7 fixed, Catholic variable Sunday) ---
    has_ang_baptism_107 = "baptism" in ang_name("01-07")
    cat_baptism_mmdd: str | None = None
    for _dd in range(7, 14):
        _mmdd = f"01-{_dd:02d}"
        if any("baptism" in n for n in cat_names(_mmdd)):
            cat_baptism_mmdd = _mmdd
            break
    if has_ang_baptism_107 and cat_baptism_mmdd and cat_baptism_mmdd != "01-07":
        ang_on_cat_baptism = ang.get(f"{year}-{cat_baptism_mmdd}")
        ang_real_on_cat_baptism = (
            ang_on_cat_baptism is not None and _is_real_anglican(ang_on_cat_baptism)
        )
        if ang_real_on_cat_baptism:
            if _hash_select(date(year, 1, 7)) == 0:
                flags.overrides[cat_baptism_mmdd] = "BAPTISM_ANG"
        else:
            flags.overrides["01-07"] = "BAPTISM_CAT"

    return flags


# ---------------------------------------------------------------------------
# Public API — year cache
# ---------------------------------------------------------------------------

def build_year_cache(
    year: int,
    ang_data: dict[str, AnglicanDay],
    cat_data: dict[str, list[CatholicFeast]],
) -> CrossDateFlags:
    """Precompute cross-date flags for a full calendar year.

    ang_data: {iso_date_string: AnglicanDay}
    cat_data: {iso_date_string: [CatholicFeast, …]}
    """
    return _precompute_flags(year, ang_data, cat_data)


# ---------------------------------------------------------------------------
# Public API — combined result
# ---------------------------------------------------------------------------

def get_combined_result(
    d: date,
    ang_day: AnglicanDay,
    flags: CrossDateFlags,
) -> CombinedResult:
    """Classify *d* and return a CombinedResult using precomputed cross-date flags."""
    mmdd = d.strftime("%m-%d")
    cat_feasts_raw = get_catholic_feasts(d)

    ang_real = _is_real_anglican(ang_day)

    # Filter ProperOfTime entries for combined-mode display rules
    cat_feasts = _filter_proper_of_time(cat_feasts_raw, ang_real=ang_real, combined=True)
    cat_real = bool(cat_feasts)

    ang_name_base = _base_name(ang_day)
    ang_season = ang_day.season
    ang_week = ang_day.week

    def _make(cat: str, src: str, flag: bool, flag_src: str) -> CombinedResult:
        wiki_url = ang_day.wiki_url if src == "anglican" else ""
        return CombinedResult(
            category=cat,
            display_name=_pick_display(src, ang_name_base, cat_feasts),
            source=src,
            flag=flag,
            flag_source=flag_src,
            season=ang_season,
            week=ang_week,
            wiki_url=wiki_url,
            anglican=ang_day,
        )

    # --- Cross-date overrides ---
    override = flags.overrides.get(mmdd)
    if override == "EPHREM_ANG":
        return _make("CROSS_DATE", "anglican", False, "")
    if override == "FISHER_CAT":
        return CombinedResult(
            category="CROSS_DATE",
            display_name=cat_feasts[0].name if cat_feasts else "",
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )
    if override in ("AUGUSTINE_ANG", "PHILIPJAMES_ANG", "CYPRIAN_ANG", "BAPTISM_ANG"):
        return _make("CROSS_DATE", "anglican", False, "")
    if override in ("ELIZABETH_CAT", "BAPTISM_CAT"):
        return CombinedResult(
            category="CROSS_DATE",
            display_name=cat_feasts[0].name if cat_feasts else "",
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # --- Epiphany: always Anglican Jan 6, never Catholic promoted date ---
    if mmdd == "01-06" and ang_real and "epiphany" in ang_name_base.lower():
        return _make("ANG_ONLY", "anglican", True, "anglican")

    if cat_real and any("epiphany" in f.name.lower() for f in cat_feasts) and mmdd != "01-06":
        cat_feasts = [f for f in cat_feasts if "epiphany" not in f.name.lower()]
        cat_real = bool(cat_feasts)

    # --- Holy Week ---
    if ang_day.season == "Holy Week":
        if ang_real:
            return _make("HOLY_WEEK", "anglican", False, "")
        if cat_real:
            return CombinedResult(
                category="HOLY_WEEK",
                display_name=cat_feasts[0].name,
                source="catholic",
                flag=False,
                flag_source="",
                season=ang_season,
                week=ang_week,
                anglican=ang_day,
            )
        return _make("NO_FEAST", "none", False, "")

    # --- No feast ---
    if not ang_real and not cat_real:
        return _make("NO_FEAST", "none", False, "")

    def _cat_result(cat: str, name: str, flag: bool, flag_src: str) -> CombinedResult:
        return CombinedResult(
            category=cat,
            display_name=name,
            source="catholic",
            flag=flag,
            flag_source=flag_src,
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # --- Anglican transferred feast loses to any Catholic feast ---
    if ang_real and _is_transferred(ang_day) and cat_real:
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_feasts).name, True, "catholic")

    # --- Anglican only ---
    if ang_real and not cat_real:
        return _make("ANG_ONLY", "anglican", True, "anglican")

    # --- Catholic only: hash-pick among options ---
    if not ang_real and cat_real:
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_feasts).name, True, "catholic")

    # --- Both real ---

    # SHARED_RANDOM fixed dates
    if mmdd in _SHARED_RANDOM_MMDD:
        if _hash_select(d) == 0:
            return _make("SHARED_RANDOM", "anglican", False, "")
        return _cat_result("SHARED_RANDOM", _hash_pick(d, cat_feasts).name, False, "")

    # Alias: same feast, different name strings
    alias_opt = next((o for o in cat_feasts if _is_alias(ang_name_base, o.name)), None)
    if alias_opt:
        if _hash_select(d) == 0:
            return _make("ALIAS", "anglican", False, "")
        return _cat_result("ALIAS", alias_opt.name, False, "")

    # N-way deduplicated pool selection
    pool: list[tuple[str, str]] = []   # (source, display_name)
    ang_consumed = False
    for opt in cat_feasts:
        if _same_feast(ang_name_base, opt.name):
            if not ang_consumed:
                pool.append(("shared", opt.name))
                ang_consumed = True
        else:
            pool.append(("catholic", opt.name))
    if not ang_consumed:
        pool.insert(0, ("anglican", ang_name_base))

    chosen_src, chosen_name = pool[_hash_mod(d, len(pool))]

    if chosen_src == "anglican":
        return _make("CONFLICT", "anglican", True, "anglican")
    if chosen_src == "shared":
        return CombinedResult(
            category="SHARED",
            display_name=chosen_name,
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            wiki_url=ang_day.wiki_url,
            anglican=ang_day,
        )
    return _cat_result("CONFLICT", chosen_name, True, "catholic")


def _pick_display(src: str, ang_name: str, cat_feasts: list[CatholicFeast]) -> str:
    if src == "anglican":
        return ang_name
    if src == "catholic" and cat_feasts:
        return cat_feasts[0].name
    return ""
