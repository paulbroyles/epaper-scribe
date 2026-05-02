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


# ---------------------------------------------------------------------------
# Catholic slash-segment expansion
# ---------------------------------------------------------------------------

def _expand_catholic_options(cat_feasts: list[CatholicFeast]) -> list[CatholicFeast]:
    """Expand slash-delimited CatholicFeast names into individual options.

    Romcal uses "/" to separate distinct optional commemorations that share a
    calendar date but are NOT jointly celebrated — a priest would choose one
    or none.  Each segment becomes its own CatholicFeast with the same rank
    as the parent entry.

    Example:
      "Saint George, Martyr/Saint Adalbert, Bishop and Martyr" (OPT_MEMORIAL)
      → CatholicFeast("Saint George, Martyr", "OPT_MEMORIAL")
         CatholicFeast("Saint Adalbert, Bishop and Martyr", "OPT_MEMORIAL")
    """
    expanded: list[CatholicFeast] = []
    for feast in cat_feasts:
        if "/" in feast.name:
            for seg in feast.name.split("/"):
                seg = seg.strip()
                if seg:
                    expanded.append(CatholicFeast(name=seg, rank=feast.rank))
        else:
            expanded.append(feast)
    return expanded


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
        # Only carry the Anglican wiki_url when Anglican actually wins; for
        # Catholic wins the provider should search by the saint's display name.
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

    # Expand slash-delimited Catholic entries into individual options.
    # Romcal uses "/" for distinct optional commemorations on the same date
    # that are NOT joint celebrations — each is an independent option.
    cat_opts = _expand_catholic_options(cat_feasts)

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
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_opts).name, True, "catholic")

    # --- Anglican only ---
    if ang_real and not cat_real:
        return _make("ANG_ONLY", "anglican", True, "anglican")

    # --- Catholic only: hash-pick among expanded options ---
    if not ang_real and cat_real:
        return _cat_result("CAT_ONLY", _hash_pick(d, cat_opts).name, True, "catholic")

    # --- Both real ---

    # SHARED_RANDOM fixed dates: same feast in both traditions; cycle name strings.
    if mmdd in _SHARED_RANDOM_MMDD:
        if _hash_select(d) == 0:
            return _make("SHARED_RANDOM", "anglican", False, "")
        return _cat_result("SHARED_RANDOM", _hash_pick(d, cat_opts).name, False, "")

    # Alias: same feast, different name strings — cycle between traditions' wording.
    # Check each expanded Catholic option so a slash-paired option can match.
    alias_opt = next((o for o in cat_opts if _is_alias(ang_name_base, o.name)), None)
    if alias_opt:
        if _hash_select(d) == 0:
            return _make("ALIAS", "anglican", False, "")
        return _cat_result("ALIAS", alias_opt.name, False, "")

    # Build a deduplicated options pool for N-way equal-weight selection.
    #
    # Deduplication rule: if any Catholic segment names the same saint as
    # Anglican, merge Anglican + that segment into ONE shared slot (prevents
    # double-counting the same person).  Every other Catholic segment, and
    # Anglican itself when no match is found, are independent slots.
    # hash mod N then picks one slot, giving every distinct saint an equal
    # share of years.
    #
    # Example — Apr 23 (Anglican: George; Catholic: George / Adalbert):
    #   pool = [("shared", "Saint George, Martyr"),
    #           ("catholic", "Saint Adalbert, Bishop and Martyr")]
    #   → coin flip between George and Adalbert.
    #
    # Example — plain conflict (Anglican: X; Catholic: Y):
    #   pool = [("anglican", X), ("catholic", Y)]
    #   → coin flip, same as before.
    pool: list[tuple[str, str]] = []   # (source, display_name)
    ang_consumed = False
    for opt in cat_opts:
        if _same_feast(ang_name_base, opt.name):
            if not ang_consumed:
                pool.append(("shared", opt.name))   # Anglican + this segment = one slot
                ang_consumed = True
            # else: skip — Anglican already merged; further duplicates suppressed
        else:
            pool.append(("catholic", opt.name))
    if not ang_consumed:
        pool.insert(0, ("anglican", ang_name_base))

    chosen_src, chosen_name = pool[_hash_mod(d, len(pool))]

    if chosen_src == "anglican":
        return _make("CONFLICT", "anglican", True, "anglican")
    if chosen_src == "shared":
        # Same saint in both traditions; show unflagged with Catholic segment name.
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
    # chosen_src == "catholic": a distinct Catholic-only option won
    return _cat_result("CONFLICT", chosen_name, True, "catholic")


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
