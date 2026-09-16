"""Check feast_wiki_map.json against both calendars and against Wikipedia.

The integration describes each saint's day from a verified map of observance →
Wikipedia article(s), falling back to search only for unmapped days. This script
keeps that map honest when romcal, the Anglican liturgical-calendar package, or
Wikipedia change. It reports:

  UNMAPPED   observances the calendars produce that the map doesn't cover
  STALE      map entries no longer produced in the scanned years (warning only)
  MISSING    mapped titles that no longer exist on Wikipedia
  RENAMED    mapped titles that now redirect (update to the new title)
  DISAMBIG   mapped titles that became disambiguation pages
  SUSPECT    mapped titles whose short description looks like a name list,
             artwork, or other non-subject
  NO-DESC    titles on multi-person days with no short description (the
             compact fallback shown when full sentences don't fit)

Exits 1 when anything other than STALE is found.

Usage:
    uv run python scripts/check_feast_map.py [FIRST_YEAR [LAST_YEAR]]

Years default to the current year through seven years ahead, which covers
every movable-feast collision pattern.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

_REPO = pathlib.Path(__file__).resolve().parent.parent
_COMPONENT = _REPO / "custom_components" / "epaper_scribe"
_MAP_PATH = _COMPONENT / "feast_wiki_map.json"
sys.path.insert(0, str(_COMPONENT))  # vendored `romcal`

# Distinct module name: the integration's module and the Anglican
# `liturgical_calendar` package would otherwise collide in sys.modules.
_spec = importlib.util.spec_from_file_location(
    "_epaper_lit_cal", _COMPONENT / "providers" / "liturgical_calendar.py"
)
_lit = importlib.util.module_from_spec(_spec)
sys.modules["_epaper_lit_cal"] = _lit
_spec.loader.exec_module(_lit)

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "EPaperScribe-feast-map-check/1.0 (https://github.com/paulbroyles/epaper-scribe)"
# Keep in sync with _NON_SUBJECT_DESC in providers/saints_day.py.
NON_SUBJECT = re.compile(
    r"name list|given name|surname|family name|topics referred to|"
    r"painting|sculpture|album|song\b|single by|film\b|novel\b|television",
    re.IGNORECASE,
)


def calendar_observances(first: int, last: int) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({catholic feast id: name}, {anglican day name: first date}) for the years."""
    from liturgical_calendar.liturgical import liturgical_calendar

    catholic: dict[str, str] = {}
    anglican: dict[str, str] = {}
    for year in range(first, last + 1):
        for feasts in _lit.fetch_catholic_year(year).values():
            for feast in feasts:
                catholic.setdefault(feast.feast_id, feast.name)
        d = date(year, 1, 1)
        while d.year == year:
            try:
                raw = liturgical_calendar(d)
            except Exception:
                d += timedelta(days=1)
                continue
            day = _lit.AnglicanDay(
                name=raw.get("name", ""), week=raw.get("week", ""),
                season=raw.get("season", ""), type_=raw.get("type", ""),
                wiki_url=raw.get("url", ""),
            )
            if _lit._is_real_anglican(day):
                anglican.setdefault(_lit._base_name(day), d.isoformat())
            d += timedelta(days=1)
    return catholic, anglican


def title_info(titles: list[str]) -> dict[str, dict]:
    """Existence, redirect target, disambiguation flag and short description per title."""
    info: dict[str, dict] = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "redirects": 1,
            "prop": "pageprops|description", "ppprop": "disambiguation",
            "titles": "|".join(chunk),
        })
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = json.load(resp)["query"]
        normalized = {n["from"]: n["to"] for n in data.get("normalized", [])}
        redirects = {r["from"]: r["to"] for r in data.get("redirects", [])}
        pages = {p["title"]: p for p in data.get("pages", {}).values()}
        for title in chunk:
            name = normalized.get(title, title)
            final = redirects.get(name, name)
            page = pages.get(final, {})
            info[title] = {
                "final": final,
                "exists": bool(page) and "missing" not in page and "invalid" not in page,
                "disambig": "disambiguation" in page.get("pageprops", {}),
                "desc": page.get("description", ""),
            }
        time.sleep(0.5)
    return info


def main() -> int:
    this_year = datetime.now().year
    first = int(sys.argv[1]) if len(sys.argv) > 1 else this_year
    last = int(sys.argv[2]) if len(sys.argv) > 2 else first + 7

    feast_map = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    print(f"Scanning calendars {first}–{last}…", file=sys.stderr)
    catholic, anglican = calendar_observances(first, last)

    problems: list[str] = []
    warnings: list[str] = []
    for fid, name in sorted(catholic.items()):
        if fid not in feast_map["catholic"]:
            problems.append(f"UNMAPPED  catholic  {fid!r}  ({name})")
    for name in sorted(anglican):
        if name not in feast_map["anglican"]:
            problems.append(f"UNMAPPED  anglican  {name!r}  (first seen {anglican[name]})")
    for cal, seen in (("catholic", catholic), ("anglican", anglican)):
        for key in sorted(set(feast_map[cal]) - set(seen)):
            warnings.append(f"STALE     {cal}  {key!r}")

    uses: dict[str, list[tuple[str, str, bool]]] = {}
    for cal in ("catholic", "anglican"):
        for key, entry in feast_map[cal].items():
            short = len(entry.get("titles", [])) > 1   # needs short descriptions for the compact fallback
            for title in entry.get("titles", []) + ([entry["image"]] if entry.get("image") else []):
                uses.setdefault(title, []).append((cal, key, short))
    print(f"Checking {len(uses)} Wikipedia titles…", file=sys.stderr)
    info = title_info(sorted(uses))
    for title, where in sorted(uses.items()):
        i = info[title]
        label = f"{title!r}  ← {where[0][0]} {where[0][1]!r}" + (f" (+{len(where) - 1} more)" if len(where) > 1 else "")
        if not i["exists"]:
            problems.append(f"MISSING   {label}")
        elif i["disambig"]:
            problems.append(f"DISAMBIG  {label}")
        elif i["final"] != title:
            problems.append(f"RENAMED   {label}  → {i['final']!r}")
        elif NON_SUBJECT.search(i["desc"]):
            problems.append(f"SUSPECT   {label}  ({i['desc']})")
        elif any(short for _, _, short in where) and not i["desc"]:
            problems.append(f"NO-DESC   {label}")

    for line in problems + warnings:
        print(line)
    print(
        f"\n{len(catholic)} Catholic and {len(anglican)} Anglican observances; "
        f"{len(problems)} problem(s), {len(warnings)} warning(s).",
        file=sys.stderr,
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
