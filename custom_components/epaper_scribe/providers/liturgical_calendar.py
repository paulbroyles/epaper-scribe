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




# ---------------------------------------------------------------------------
# Module-level singletons (lazy-initialised)
# ---------------------------------------------------------------------------

_romcal = Romcal(localized_calendar=GeneralRoman_En)
_year_cache: dict[int, dict[str, list[CatholicFeast]]] = {}
_season_cache: dict[int, dict[str, str]] = {}  # {year: {iso_date: display_season}}

# romcal Season enum values to include (others, e.g. sub-period strings, are ignored).
_ROMCAL_SEASONS: frozenset[str] = frozenset({
    "ADVENT", "CHRISTMAS_TIME", "ORDINARY_TIME",
    "LENT", "PASCHAL_TRIDUUM", "EASTER_TIME",
})


def _romcal_season_display(s: str) -> str:
    """Convert 'EASTER_TIME' → 'Easter Time', 'ADVENT' → 'Advent', etc."""
    return s.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Catholic calendar generation
# ---------------------------------------------------------------------------


def _build_year_calendar(year: int) -> None:
    """Generate the full Roman Catholic calendar for *year* and populate caches."""
    raw = _romcal.generate_calendar(year)

    calendar: dict[str, list[CatholicFeast]] = {}
    seasons: dict[str, str] = {}
    for date_str, days in raw.items():
        # Season: take the first day's seasons list (highest-precedence entry).
        # days[0].seasons is a list like ["LENT"] or ["EASTER_TIME"].
        if days:
            for s in days[0].seasons:
                if s in _ROMCAL_SEASONS:
                    seasons[date_str] = _romcal_season_display(s)
                    break

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

    _year_cache[year] = calendar
    _season_cache[year] = seasons


def _ensure_year(year: int) -> None:
    if year not in _year_cache:
        _build_year_calendar(year)


def get_catholic_feasts(d: date) -> list[CatholicFeast]:
    """Return Catholic feast(s) for date *d*.

    Returns an empty list on ordinary weekdays with no celebration.
    Multiple entries are possible (e.g. two optional memorials on the same
    date). ProperOfTime entries are included; callers in combined mode
    should apply _filter_proper_of_time() before further processing.
    """
    _ensure_year(d.year)
    return _year_cache[d.year].get(d.isoformat(), [])


def get_catholic_season(d: date) -> str:
    """Return the display season string for *d* in the Roman Catholic calendar.

    Returns one of: "Advent", "Christmas", "Ordinary", "Lent", "Holy Week",
    "Easter" — or "" if romcal has no season data for the date.
    """
    _ensure_year(d.year)
    return _season_cache[d.year].get(d.isoformat(), "")


def fetch_catholic_year(year: int) -> dict[str, list[CatholicFeast]]:
    """Return all Catholic feasts for *year* as {iso_date: [CatholicFeast]}.

    Runs synchronously; intended to be called via async_add_executor_job.
    """
    _ensure_year(year)
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
    allow_ids: frozenset[str] = frozenset(),
) -> list[CatholicFeast]:
    """Filter ProperOfTime entries for combined-mode display.

    In Catholic-only mode (combined=False) all feasts pass through unchanged.

    In combined mode:
    - Sanctoral entries always pass through.
    - Sacred Heart passes through (treated as a saint's day).
    - Feasts whose ID is in *allow_ids* pass through — used when the cross-date
      algorithm has determined that a ProperOfTime feast (e.g. Baptism of the
      Lord) wins its cross-date resolution and must surface in combined mode.
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
        elif feast.feast_id in allow_ids:
            filtered.append(feast)  # cross-date winner
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
# Cross-date feast identity pairs
#
# Each entry links a Catholic romcal feast_id (left) to a compiled regex
# (right) matched against _base_name(ang_day).lower().
#
# Using explicit Catholic IDs + name-regex avoids the false positives that
# arise from shared given names across different saints (e.g. "Augustine of
# Canterbury" ≠ "Augustine of Hippo") or generic words (e.g. "elizabeth"
# in the Visitation feast "…Mary to Elizabeth").
#
# To extend to other national calendars in future, add more entries here.
# ---------------------------------------------------------------------------

_CROSS_DATE_PAIRS: list[tuple[str, str, re.Pattern[str] | None]] = [
    # (catholic_feast_id,                                          ang_wiki_slug,             fallback_regex)
    ("baptism_of_the_lord",
     "Baptism_of_the_Lord",                                        re.compile(r"baptism")),
    ("philip_and_james_apostles",
     "Philip_the_Apostle",                                         re.compile(r"philip\s+and\s+james")),
    ("ephrem_the_syrian_deacon",
     "Ephrem_the_Syrian",                                          re.compile(r"ephrem")),
    ("cornelius_i_pope_and_cyprian_of_carthage_bishop_martyrs",
     "Cyprian",                                                     re.compile(r"cyprian")),
    ("elizabeth_of_hungary_religious",
     "Elisabeth_of_Hungary",                                        re.compile(r"elizabeth\s+of\s+hungary")),
    ("augustine_of_canterbury_bishop",
     "Augustine_of_Canterbury",                                     re.compile(r"augustine\s+of\s+canterbury")),
]

# Derived lookup maps (built once at module load)
_CAT_ID_TO_ANG_CROSS: dict[str, tuple[str, re.Pattern[str] | None]] = {
    cid: (slug, pat) for cid, slug, pat in _CROSS_DATE_PAIRS
}
_ANG_SLUG_TO_CAT_ID: dict[str, str] = {
    slug: cid for cid, slug, _pat in _CROSS_DATE_PAIRS
}
_ANG_FALLBACK_PATS: list[tuple[re.Pattern[str], str]] = [
    (pat, cid) for cid, _slug, pat in _CROSS_DATE_PAIRS if pat is not None
]


def _ang_matches_cross_date(
    ang_day: AnglicanDay,
    slug: str,
    pat: re.Pattern[str] | None,
) -> bool:
    """Return True if *ang_day* represents the feast identified by *slug*/*pat*.

    Matching strategy:
    - If the Anglican entry has a wiki_url, match on the URL slug (authoritative).
    - Otherwise fall back to the regex pattern against the base name.
    """
    if ang_day.wiki_url:
        return ang_day.wiki_url.endswith("/" + slug)
    if pat is not None:
        return bool(pat.search(_base_name(ang_day).lower()))
    return False


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
# Cross-date resolution (on-demand, full-year lookup)
# ---------------------------------------------------------------------------

def _cross_date_decision(
    ang_d: date,
    cat_d: date,
    ang_year: dict[str, AnglicanDay],
    cat_year: dict[str, list[CatholicFeast]],
) -> str:
    """Return the decision for a (ang_date, cat_date) cross-date pair.

    Decision matrix:
      ang_comp = real Anglican content on cat_date
      cat_comp = Catholic content on ang_date

      (ang_comp=No,  cat_comp=Yes) → "cat_claims"   — Catholic date wins
      (ang_comp=Yes, cat_comp=No)  → "ang_claims"   — Anglican date wins
      (ang_comp=No,  cat_comp=No)  → hash(ang_date) 0→ang, 1→cat
      (ang_comp=Yes, cat_comp=Yes) → hash(ang_date) 0→ang, 1→cat
    """
    ang_at_cat = ang_year.get(cat_d.isoformat())
    ang_comp = ang_at_cat is not None and _is_real_anglican(ang_at_cat)
    cat_comp = bool(cat_year.get(ang_d.isoformat()))

    if not ang_comp and cat_comp:
        return "cat_claims"
    if ang_comp and not cat_comp:
        return "ang_claims"
    # Both or neither have cross-tradition competition: hash on ang_date
    return "ang_claims" if _hash_select(ang_d) == 0 else "cat_claims"


# ---------------------------------------------------------------------------
# Public API — combined result
# ---------------------------------------------------------------------------

def get_combined_result(
    d: date,
    ang_day: AnglicanDay,
    ang_year: dict[str, AnglicanDay],
) -> CombinedResult:
    """Classify *d* and return a CombinedResult.

    Cross-date detection is performed on-demand by searching the full Anglican
    and Catholic year calendars for same-feast matches on different dates.
    No pre-scan pass is required — the year caches are already in memory.

    ang_year: {iso_date_string: AnglicanDay} for the full year.
    """
    mmdd = d.strftime("%m-%d")
    d_iso = d.isoformat()
    cat_year = fetch_catholic_year(d.year)
    cat_feasts_raw = cat_year.get(d_iso, [])

    ang_real = _is_real_anglican(ang_day)
    ang_name_base = _base_name(ang_day)
    ang_season = ang_day.season
    ang_week = ang_day.week

    # -----------------------------------------------------------------
    # Cross-date analysis: find same feast at a different date in the
    # other tradition, then decide which date claims it.
    # -----------------------------------------------------------------
    suppress_cat_ids: set[str] = set()   # Catholic feast IDs to remove at this date
    allow_pot_ids: frozenset[str] = frozenset()  # ProperOfTime IDs allowed here
    force_cat: bool = False              # Anglican feast belongs at its Catholic date

    # 1) From the Catholic side: for each Catholic feast at this date, look up
    #    its feast_id in _CAT_ID_TO_ANG_CROSS to get the Anglican wiki slug and
    #    fallback regex, then search ang_year for a matching entry on a different
    #    date.
    _allow_pot: set[str] = set()
    for cat_feast in cat_feasts_raw:
        cross = _CAT_ID_TO_ANG_CROSS.get(cat_feast.feast_id)
        if cross is None:
            continue  # not a known cross-date feast
        slug, pat = cross
        # Search Anglican year for the matching feast on a different date
        for ang_iso, ang_check in ang_year.items():
            if ang_iso == d_iso:
                continue
            if not _is_real_anglican(ang_check):
                continue
            if not _ang_matches_cross_date(ang_check, slug, pat):
                continue
            # Found: Anglican ang_iso ↔ Catholic d (current)
            ang_d = date.fromisoformat(ang_iso)
            decision = _cross_date_decision(ang_d, d, ang_year, cat_year)
            if decision == "ang_claims":
                suppress_cat_ids.add(cat_feast.feast_id)
            else:
                if cat_feast.is_proper_of_time:
                    _allow_pot.add(cat_feast.feast_id)
            break  # first matching Anglican entry is sufficient

    allow_pot_ids = frozenset(_allow_pot)

    # 2) From the Anglican side: if Anglican has a real feast here, identify
    #    its cross-date Catholic counterpart (by URL slug if available, regex
    #    fallback otherwise), then look up the Catholic date in cat_year.
    if ang_real:
        cat_id_found: str | None = None
        if ang_day.wiki_url:
            slug = ang_day.wiki_url.rsplit("/", 1)[-1]
            cat_id_found = _ANG_SLUG_TO_CAT_ID.get(slug)
        if cat_id_found is None:
            ang_base_lower = ang_name_base.lower()
            for pat, cat_id in _ANG_FALLBACK_PATS:
                if pat.search(ang_base_lower):
                    cat_id_found = cat_id
                    break
        if cat_id_found is not None:
            for cat_iso, cat_feasts_there in cat_year.items():
                if cat_iso == d_iso:
                    continue
                if not any(f.feast_id == cat_id_found for f in cat_feasts_there):
                    continue
                # Found: Anglican d (current) ↔ Catholic cat_iso
                cat_d = date.fromisoformat(cat_iso)
                decision = _cross_date_decision(d, cat_d, ang_year, cat_year)
                if decision == "cat_claims":
                    force_cat = True
                break  # found the Catholic date for this pair

    # -----------------------------------------------------------------
    # Apply cross-date results before normal resolution
    # -----------------------------------------------------------------

    def _make(cat: str, src: str, flag: bool, flag_src: str,
              cf: list[CatholicFeast] | None = None) -> CombinedResult:
        wiki_url = ang_day.wiki_url if src == "anglican" else ""
        return CombinedResult(
            category=cat,
            display_name=_pick_display(src, ang_name_base, cf or []),
            source=src,
            flag=flag,
            flag_source=flag_src,
            season=ang_season,
            week=ang_week,
            wiki_url=wiki_url,
            anglican=ang_day,
        )

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

    if force_cat:
        # Anglican feast belongs at its own Catholic date; suppress it here.
        # Show whatever Catholic content is available at this (Anglican) date.
        remaining = [
            f for f in cat_feasts_raw
            if f.feast_id not in suppress_cat_ids
        ]
        remaining = _filter_proper_of_time(remaining, ang_real=False, combined=False)
        if remaining:
            return _cat_result("CROSS_DATE", _hash_pick(d, remaining).name,
                               flag=True, flag_src="catholic")
        return _make("NO_FEAST", "none", False, "")

    # Normal path: apply suppress + ProperOfTime filter
    cat_feasts_filtered = [
        f for f in cat_feasts_raw if f.feast_id not in suppress_cat_ids
    ]
    cat_feasts = _filter_proper_of_time(
        cat_feasts_filtered, ang_real=ang_real, combined=True,
        allow_ids=allow_pot_ids,
    )
    cat_real = bool(cat_feasts)

    # If a Catholic feast was suppressed at the current (Catholic) date because
    # the Anglican date claimed it, but it's a ProperOfTime entry that would
    # otherwise have been shown as a cross-date winner, un-suppress it.
    # (allow_pot_ids handles this via _filter_proper_of_time above.)

    # --- Epiphany: always Anglican Jan 6, never Catholic promoted date ---
    if mmdd == "01-06" and ang_real and "epiphany" in ang_name_base.lower():
        return _make("ANG_ONLY", "anglican", True, "anglican", cat_feasts)

    if cat_real and any("epiphany" in f.name.lower() for f in cat_feasts) and mmdd != "01-06":
        cat_feasts = [f for f in cat_feasts if "epiphany" not in f.name.lower()]
        cat_real = bool(cat_feasts)

    # --- Holy Week ---
    if ang_day.season == "Holy Week":
        if ang_real:
            return _make("HOLY_WEEK", "anglican", False, "", cat_feasts)
        if cat_real:
            return _cat_result("HOLY_WEEK", cat_feasts[0].name, False, "")
        return _make("NO_FEAST", "none", False, "")

    # --- No feast ---
    if not ang_real and not cat_real:
        return _make("NO_FEAST", "none", False, "")

    # --- Anglican transferred feast loses to any Catholic feast ---
    if ang_real and _is_transferred(ang_day) and cat_real:
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_feasts).name, True, "catholic")

    # --- Anglican only ---
    if ang_real and not cat_real:
        return _make("ANG_ONLY", "anglican", True, "anglican", cat_feasts)

    # --- Catholic only: hash-pick among options ---
    if not ang_real and cat_real:
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_feasts).name, True, "catholic")

    # --- Both real ---

    # SHARED_RANDOM fixed dates
    if mmdd in _SHARED_RANDOM_MMDD:
        if _hash_select(d) == 0:
            return _make("SHARED_RANDOM", "anglican", False, "", cat_feasts)
        return _cat_result("SHARED_RANDOM", _hash_pick(d, cat_feasts).name, False, "")

    # Alias: same feast, different name strings
    alias_opt = next((o for o in cat_feasts if _is_alias(ang_name_base, o.name)), None)
    if alias_opt:
        if _hash_select(d) == 0:
            return _make("ALIAS", "anglican", False, "", cat_feasts)
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
        return _make("CONFLICT", "anglican", True, "anglican", cat_feasts)
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
