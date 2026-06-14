"""Generate liturgical-calendar verification tables for a given year.

Two outputs (Markdown, written to stdout):

  1. A table of every feast day in the year, showing the Anglican feast and
     type, the Catholic feast(s) and rank(s), and which tradition the combined
     calendar chooses to display.
  2. A cross-date analysis: saints that appear in both calendars on *different*
     dates (within ±10 days), plus a curated list of known cross-date pairs.

This is a verification / debugging tool — it drives the same
``get_combined_result`` logic the integration uses, so it is the quickest way
to eyeball a whole year and catch feasts that resolve oddly (e.g. devotional
titles, disambiguation collisions, cross-dated saints).

Usage:
    uv run python scripts/feast_table.py [YEAR] > feast_table_YEAR.md

YEAR defaults to the current year.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import date, datetime, timedelta

# ── Load the integration's liturgical_calendar module in isolation ──────────
# It imports the vendored `romcal` package by absolute name, so the component
# directory must be on sys.path; the module itself has no relative imports, so
# a plain spec-based load is enough (no fake-package hierarchy required).
_REPO = pathlib.Path(__file__).resolve().parent.parent
_COMPONENT = _REPO / "custom_components" / "epaper_scribe"
sys.path.insert(0, str(_COMPONENT))

# NB: a distinct module name — the integration's module and the Anglican
# `liturgical_calendar` PyPI package would otherwise collide in sys.modules.
_spec = importlib.util.spec_from_file_location(
    "_epaper_lit_cal", _COMPONENT / "providers" / "liturgical_calendar.py"
)
_lit = importlib.util.module_from_spec(_spec)
sys.modules["_epaper_lit_cal"] = _lit  # dataclass introspection looks here
_spec.loader.exec_module(_lit)

AnglicanDay = _lit.AnglicanDay
get_catholic_feasts = _lit.get_catholic_feasts
fetch_catholic_year = _lit.fetch_catholic_year
get_combined_result = _lit.get_combined_result
_is_real_anglican = _lit._is_real_anglican
_base_name = _lit._base_name
_same_feast = _lit._same_feast
_is_alias = _lit._is_alias


# ── Anglican data for the whole year ────────────────────────────────────────

def fetch_anglican_year(year: int) -> dict[str, AnglicanDay]:
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


def _esc(s: str) -> str:
    """Escape pipe characters so cell content doesn't break the Markdown table."""
    return s.replace("|", "\\|")


# ── Task 1: full-year feast table ───────────────────────────────────────────

def emit_feast_table(year: int, ang_data, cat_data) -> None:
    print(f"\n## {year} Feast Day Table\n")
    print("| Date | Day | Anglican feast | Ang type | Catholic feast(s) | Cat rank(s) | Display |")
    print("|------|-----|----------------|----------|-------------------|-------------|---------|")

    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        iso = d.isoformat()
        ang_day = ang_data.get(iso) or AnglicanDay(
            name="", week="", season="Ordinary", type_="", wiki_url=""
        )
        cat_feasts = cat_data.get(iso, [])

        ang_real = _is_real_anglican(ang_day)
        cat_real = bool(cat_feasts)
        if not ang_real and not cat_real:
            d += timedelta(days=1)
            continue

        result = get_combined_result(d, ang_day, ang_data)

        ang_feast = _base_name(ang_day) if ang_real else ""
        ang_type = ang_day.type_ if ang_real else ""
        cat_feast_str = " / ".join(f.name for f in cat_feasts) if cat_real else ""
        cat_rank_str = " / ".join(f.rank for f in cat_feasts) if cat_real else ""

        display = result.source
        if result.flag:
            display += f" ◆{result.flag_source}"

        print(
            f"| {iso} | {d.strftime('%a')} | {_esc(ang_feast)} | {_esc(ang_type)} "
            f"| {_esc(cat_feast_str)} | {_esc(cat_rank_str)} | {_esc(display)} |"
        )
        d += timedelta(days=1)


# ── Task 2: same saint, different date ──────────────────────────────────────

def emit_cross_date(year: int, ang_data, cat_data) -> None:
    print("\n\n## Same Saint, Different Date (±10 days)\n")

    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    ang_feasts = [
        (d_iso, _base_name(day))
        for d_iso, day in ang_data.items()
        if _is_real_anglican(day)
    ]

    for ang_iso, ang_name in ang_feasts:
        ang_date = date.fromisoformat(ang_iso)
        for delta in range(-10, 11):
            if delta == 0:
                continue
            cat_date = ang_date + timedelta(days=delta)
            if cat_date.year != year:
                continue
            for cf in cat_data.get(cat_date.isoformat(), []):
                if _same_feast(ang_name, cf.name) or _is_alias(ang_name, cf.name):
                    key = (ang_iso, cat_date.isoformat())
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((
                        ang_name,
                        ang_iso,
                        cat_date.isoformat(),
                        f"Catholic: {cf.name} (Δ{delta:+d}d)",
                    ))

    rows.sort(key=lambda r: r[1])

    print("| Saint | Anglican date | Catholic date | Notes |")
    print("|-------|--------------|--------------|-------|")
    for saint, ang_d, cat_d, notes in rows:
        print(f"| {_esc(saint)} | {ang_d} | {cat_d} | {_esc(notes)} |")


def main() -> None:
    year = datetime.now().year
    if len(sys.argv) > 1:
        try:
            year = int(sys.argv[1])
        except ValueError:
            print(f"Invalid year: {sys.argv[1]!r}", file=sys.stderr)
            raise SystemExit(2)

    print(f"Fetching Anglican data for {year}...", file=sys.stderr)
    ang_data = fetch_anglican_year(year)
    print(f"  {len(ang_data)} days", file=sys.stderr)

    print(f"Fetching Catholic data for {year}...", file=sys.stderr)
    cat_data = fetch_catholic_year(year)
    print(f"  {len(cat_data)} feast days", file=sys.stderr)

    print(f"# Liturgical Calendar — {year}")
    emit_feast_table(year, ang_data, cat_data)
    emit_cross_date(year, ang_data, cat_data)


if __name__ == "__main__":
    main()
