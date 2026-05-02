"""Combined Anglican + Catholic calendar selection logic.

Implements the rule set designed for E-Paper Scribe's combined calendar mode.
All selection is deterministic for a given date: same date always produces the
same result within a year (hash-based randomisation) and the same cross-date
flag state (precomputed once per year).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from .catholic_calendar import CatholicFeast, get_catholic_feasts

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

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
# Alias pairs: same celebration, different names
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

def _hash_select(d: date) -> int:
    """Return 0 or 1 deterministically from the date string."""
    digest = hashlib.md5(d.isoformat().encode()).hexdigest()
    return int(digest, 16) % 2


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
    "07-26",  # Parents of BVM / Joachim and Anne  (new — alias)
    "07-29",  # Mary, Martha and Lazarus / Saint Martha
    "08-06",  # Transfiguration
    "09-29",  # Michael and All Angels / Michael Gabriel Raphael
    "12-08",  # Conception of BVM / Immaculate Conception
})


# ---------------------------------------------------------------------------
# Cross-date flag precomputation
# ---------------------------------------------------------------------------

@dataclass
class _CrossDateFlags:
    """Precomputed per-year cross-date rule outcomes.

    Each flag entry maps an MM-DD key to a display override instruction.
    """
    overrides: dict[str, str] = field(default_factory=dict)  # mmdd → rule label


def _precompute_flags(
    year: int,
    ang: dict[str, AnglicanDay],
    cat: dict[str, list[CatholicFeast]],
) -> _CrossDateFlags:
    flags = _CrossDateFlags()

    def ang_name(mmdd: str) -> str:
        day = ang.get(f"{year}-{mmdd}")
        return _base_name(day).lower() if day else ""

    def cat_names(mmdd: str) -> list[str]:
        return [f.name.lower() for f in cat.get(f"{year}-{mmdd}", [])]

    # --- Ephrem rule (Jun 9 + Jun 10) ---
    # Force Anglican on both dates when Anglican has Columba Jun 9 + Ephrem Jun 10.
    if "columba" in ang_name("06-09") and "ephrem" in ang_name("06-10"):
        flags.overrides["06-09"] = "EPHREM_ANG"   # force Anglican (Columba)
        flags.overrides["06-10"] = "EPHREM_ANG"   # force Anglican (Ephrem)

    # --- Fisher+More / Goretti rule (Jun 22 + Jul 6) ---
    # Catholic Fisher+More lives on Jun 22; Anglican Fisher+More on Jul 6.
    # If Catholic wins Jun 22 (hash=1), force Catholic Goretti on Jul 6 to
    # avoid seeing Fisher+More twice.
    has_ang_alban_622 = "alban" in ang_name("06-22")
    has_cat_fisher_622 = any("fisher" in n for n in cat_names("06-22"))
    has_ang_fisher_706 = "fisher" in ang_name("07-06") or "more" in ang_name("07-06")
    if has_ang_alban_622 and has_cat_fisher_622 and has_ang_fisher_706:
        if _hash_select(date(year, 6, 22)) == 1:  # Catholic wins Jun 22
            flags.overrides["07-06"] = "FISHER_CAT"  # force Catholic (Goretti)

    # --- Augustine of Canterbury rule (May 26 + May 27) ---
    # Anglican May 26, Catholic May 27 — if Anglican wins May 26, force Anglican
    # for May 27 so Augustine appears once and on the Anglican date.
    has_ang_aug_526 = "augustine" in ang_name("05-26")
    has_cat_aug_527 = any("augustine" in n for n in cat_names("05-27"))
    if has_ang_aug_526 and has_cat_aug_527:
        if _hash_select(date(year, 5, 26)) == 0:  # Anglican wins May 26
            flags.overrides["05-27"] = "AUGUSTINE_ANG"

    # --- Philip and James rule (Anglican May 1 + Catholic May 3) ---
    a501 = ang.get(f"{year}-05-01")
    has_ang_pj_501 = (
        a501 and "philip" in _base_name(a501).lower()
        and "james" in _base_name(a501).lower()
    )
    has_cat_pj_503 = any("philip" in n for n in cat_names("05-03"))
    if has_ang_pj_501 and has_cat_pj_503:
        if _hash_select(date(year, 5, 1)) == 0:  # Anglican wins May 1
            flags.overrides["05-03"] = "PHILIPJAMES_ANG"

    # --- Elizabeth of Hungary rule (Anglican Nov 17 + Catholic Nov 18) ---
    has_ang_eliz_1117 = "elizabeth" in ang_name("11-17")
    has_cat_eliz_1118 = any("elizabeth" in n for n in cat_names("11-18"))
    if has_ang_eliz_1117 and has_cat_eliz_1118:
        if _hash_select(date(year, 11, 17)) == 1:  # Catholic wins Nov 17
            flags.overrides["11-18"] = "ELIZABETH_CAT"

    # --- Cyprian of Carthage rule (Anglican Sep 15 + Catholic Sep 16) ---
    # Anglican: Cyprian alone on Sep 15.
    # Catholic: Cornelius and Cyprian together on Sep 16.
    # If Anglican wins Sep 15 (Cyprian shown), force Anglican on Sep 16 too so
    # Cyprian does not appear on both consecutive days.
    has_ang_cyprian_915 = "cyprian" in ang_name("09-15")
    has_cat_cyprian_916 = any("cyprian" in n for n in cat_names("09-16"))
    if has_ang_cyprian_915 and has_cat_cyprian_916:
        if _hash_select(date(year, 9, 15)) == 0:  # Anglican wins Sep 15
            flags.overrides["09-16"] = "CYPRIAN_ANG"

    # --- Baptism of Christ rule (Anglican Jan 7 fixed, Catholic variable Sunday) ---
    # The Catholic Baptism of the Lord falls on the Sunday after Epiphany (Jan 7–13).
    # Anglican always places it on Jan 7 (fixed).
    # Strategy:
    #   • If the Catholic Baptism date has a competing Anglican saint, apply the
    #     standard cross-date pattern: hash on Jan 7; if Anglican wins, force
    #     Anglican on the Catholic Baptism date too.
    #   • If the Catholic Baptism date is uncontested (no real Anglican feast),
    #     the Baptism will naturally dominate that date; suppress the duplicate
    #     Anglican Baptism on Jan 7 by forcing Catholic there instead.
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
            # Contested Catholic Baptism date → hash on Jan 7
            if _hash_select(date(year, 1, 7)) == 0:  # Anglican wins Jan 7
                flags.overrides[cat_baptism_mmdd] = "BAPTISM_ANG"
        else:
            # Uncontested Catholic Baptism date → suppress Anglican Jan 7
            flags.overrides["01-07"] = "BAPTISM_CAT"

    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_combined_result(
    d: date,
    ang_day: AnglicanDay,
    flags: _CrossDateFlags,
) -> CombinedResult:
    """Classify d and return a CombinedResult using precomputed cross-date flags."""
    mmdd = d.strftime("%m-%d")
    cat_feasts = get_catholic_feasts(d)

    ang_real = _is_real_anglican(ang_day)
    cat_real = bool(cat_feasts)

    ang_name_base = _base_name(ang_day)
    ang_season = ang_day.season
    ang_week = ang_day.week

    def _make(cat: str, src: str, flag: bool, flag_src: str) -> CombinedResult:
        return CombinedResult(
            category=cat,
            display_name=_pick_display(src, ang_name_base, cat_feasts),
            source=src,
            flag=flag,
            flag_source=flag_src,
            season=ang_season,
            week=ang_week,
            wiki_url=ang_day.wiki_url,
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
        # Catholic promoted Epiphany on a different date — skip
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

    # --- Anglican transferred feast loses to any Catholic feast ---
    if ang_real and _is_transferred(ang_day) and cat_real:
        return CombinedResult(
            category="CAT_ONLY",
            display_name=cat_feasts[0].name,
            source="catholic",
            flag=True,
            flag_source="catholic",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # --- Anglican only ---
    if ang_real and not cat_real:
        return _make("ANG_ONLY", "anglican", True, "anglican")

    # --- Catholic only ---
    if not ang_real and cat_real:
        return CombinedResult(
            category="CAT_ONLY",
            display_name=cat_feasts[0].name,
            source="catholic",
            flag=True,
            flag_source="catholic",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # --- Both real ---

    # SHARED_RANDOM fixed dates
    if mmdd in _SHARED_RANDOM_MMDD:
        h = _hash_select(d)
        if h == 0:
            return _make("SHARED_RANDOM", "anglican", False, "")
        return CombinedResult(
            category="SHARED_RANDOM",
            display_name=cat_feasts[0].name,
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # Alias (same feast, different name string)
    if any(_is_alias(ang_name_base, f.name) for f in cat_feasts):
        h = _hash_select(d)
        if h == 0:
            return _make("ALIAS", "anglican", False, "")
        return CombinedResult(
            category="ALIAS",
            display_name=cat_feasts[0].name,
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            anglican=ang_day,
        )

    # Same saint — prefer Catholic string
    if any(_same_feast(ang_name_base, f.name) for f in cat_feasts):
        matched = next(f for f in cat_feasts if _same_feast(ang_name_base, f.name))
        return CombinedResult(
            category="SHARED",
            display_name=matched.name,
            source="catholic",
            flag=False,
            flag_source="",
            season=ang_season,
            week=ang_week,
            wiki_url=ang_day.wiki_url,
            anglican=ang_day,
        )

    # Conflict — hash-based stable selection so the same feast day alternates
    # between traditions across years, maximising the variety of saints seen.
    h = _hash_select(d)
    if h == 0:
        return _make("CONFLICT", "anglican", True, "anglican")
    return CombinedResult(
        category="CONFLICT",
        display_name=cat_feasts[0].name,
        source="catholic",
        flag=True,
        flag_source="catholic",
        season=ang_season,
        week=ang_week,
        anglican=ang_day,
    )


def _pick_display(src: str, ang_name: str, cat_feasts: list[CatholicFeast]) -> str:
    if src == "anglican":
        return ang_name
    if src == "catholic" and cat_feasts:
        return cat_feasts[0].name
    return ""


def build_year_cache(
    year: int,
    ang_data: dict[str, AnglicanDay],
    cat_data: dict[str, list[CatholicFeast]],
) -> _CrossDateFlags:
    """Precompute cross-date flags for a full year.

    ang_data: {iso_date_string: AnglicanDay}
    cat_data: {iso_date_string: [CatholicFeast, …]}
    """
    return _precompute_flags(year, ang_data, cat_data)
