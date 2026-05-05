"""
Full year calendar chart for 2027: Anglican | Roman Catholic | Combined resolution.

Uses epaper-scribe's liturgical_calendar provider as a black box.

Run from repo root with the epaper-scribe venv:
    .venv/bin/python3 scripts/feast_table_2027.py
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

# ── Load our liturgical_calendar.py under an alias so it doesn't shadow
#    the Anglican `liturgical_calendar` package that's installed in the venv.
_PROVIDERS = Path(__file__).parent.parent / "custom_components/epaper_scribe/providers"
_ROMCAL    = Path(__file__).parent.parent.parent / "python-romcal"
sys.path.insert(0, str(_ROMCAL))

_spec = importlib.util.spec_from_file_location(
    "epaper_litur",                          # alias — avoids name collision
    _PROVIDERS / "liturgical_calendar.py",
)
_lc = importlib.util.module_from_spec(_spec)
sys.modules["epaper_litur"] = _lc           # must be registered BEFORE exec
_spec.loader.exec_module(_lc)               # now dataclasses can resolve __module__

AnglicanDay         = _lc.AnglicanDay
fetch_catholic_year = _lc.fetch_catholic_year
get_combined_result = _lc.get_combined_result
_is_real_anglican   = _lc._is_real_anglican
_base_name          = _lc._base_name

# ── Anglican data (from the installed liturgical-calendar package) ─────────────

def fetch_anglican_year(year: int) -> dict[str, AnglicanDay]:
    from liturgical_calendar.liturgical import liturgical_calendar as ang_cal
    result: dict[str, AnglicanDay] = {}
    d, end = date(year, 1, 1), date(year, 12, 31)
    while d <= end:
        try:
            cal = ang_cal(d)
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

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    year = 2027

    print(f"Fetching Anglican data for {year}…", file=sys.stderr)
    ang_data = fetch_anglican_year(year)

    print(f"Fetching Catholic data for {year}…", file=sys.stderr)
    cat_data = fetch_catholic_year(year)

    print("Cross-date resolution is now on-demand per date.", file=sys.stderr)

    RANK = {"SOLEMNITY": "Sol", "FEAST": "Fst", "MEMORIAL": "Mem", "OPT_MEMORIAL": "Opt"}

    def esc(s: str) -> str:
        return s.replace("|", "\\|")

    print("| Date       | Day | Anglican                         | Ang type           | Catholic feast(s)                              | Rank    | Combined                                     |")
    print("|------------|-----|----------------------------------|--------------------|------------------------------------------------|---------|----------------------------------------------|")

    d, end = date(year, 1, 1), date(year, 12, 31)
    while d <= end:
        iso        = d.isoformat()
        ang_day    = ang_data.get(iso, AnglicanDay("", "", "", ""))
        cat_feasts = cat_data.get(iso, [])

        ang_real = _is_real_anglican(ang_day)
        cat_real = bool(cat_feasts)

        if not ang_real and not cat_real:
            d += timedelta(days=1)
            continue

        ang_name  = esc(_base_name(ang_day)) if ang_real else ""
        ang_type  = esc(ang_day.type_)       if ang_real else ""
        cat_names = " / ".join(esc(f.name) for f in cat_feasts) if cat_real else ""
        cat_ranks = " / ".join(RANK.get(f.rank, f.rank) for f in cat_feasts) if cat_real else ""

        res  = get_combined_result(d, ang_day, ang_data)
        cat  = res.category
        src  = res.source
        disp = esc(res.display_name)

        if   cat == "NO_FEAST":                        combined = "—"
        elif cat == "SHARED":                          combined = f"≡ {disp}"
        elif cat == "SHARED_RANDOM":                   combined = f"~ {disp}"
        elif cat == "ALIAS":                           combined = f"≈ {disp}"
        elif cat == "HOLY_WEEK":                       combined = f"✝ {disp}"
        elif cat == "CROSS_DATE" and src == "anglican": combined = f"† 🅐 {disp}"
        elif cat == "CROSS_DATE" and src == "catholic": combined = f"† 🅒 {disp}"
        elif cat == "CONFLICT"   and src == "anglican": combined = f"🅐! {disp}"
        elif cat == "CONFLICT"   and src == "catholic": combined = f"🅒! {disp}"
        elif src == "anglican":                         combined = f"🅐 {disp}"
        elif src == "catholic":                         combined = f"🅒 {disp}"
        else:                                           combined = disp

        print(f"| {iso} | {d.strftime('%a')} | {ang_name:<32} | {ang_type:<18} "
              f"| {cat_names:<46} | {cat_ranks:<7} | {combined} |")
        d += timedelta(days=1)

    print()
    print("**Legend:**  "
          "`≡` same feast  "
          "`~` same reality, tradition hash-chosen  "
          "`≈` alias  "
          "`✝` Holy Week  "
          "`†` cross-date override  "
          "`🅐` Anglican wins  `🅒` Catholic wins  "
          "`!` conflict (hash-chosen)")

if __name__ == "__main__":
    main()
