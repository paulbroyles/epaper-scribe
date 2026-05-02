"""
Production-exact PNG test renderer.

Replicates the saints_day provider pipeline exactly — same data sources,
same render call.

Usage:
    uv run scripts/render_test_pngs.py [options] [YYYY-MM-DD ...]

Options:
    --name-font PATH   TrueType font for the saint name header
    --body-font PATH   TrueType font for description / role / tag text
                       (omit either to use PIL bitmap default for that element)

Outputs /tmp/epaper_scribe_<label>_<date>.png for each date.
If no dates are given, renders a default selection of test dates.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote

# ---------------------------------------------------------------------------
# Bootstrap: load component modules without a running HA instance
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
_COMP = _ROOT / "custom_components" / "epaper_scribe"
_PROV = _COMP / "providers"


def _make_pkg(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__package__ = name
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


def _load(pkg_name: str, sub: str, file: Path) -> types.ModuleType:
    full = f"{pkg_name}.{sub}"
    spec = importlib.util.spec_from_file_location(full, str(file), submodule_search_locations=[])
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg_name
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


_make_pkg("epaper_scribe", _COMP)
_make_pkg("epaper_scribe.providers", _PROV)

const_mod      = _load("epaper_scribe", "const",       _COMP / "const.py")
saint_name_mod = _load("epaper_scribe", "saint_name",  _COMP / "saint_name.py")
cat_mod        = _load("epaper_scribe.providers", "catholic_calendar", _PROV / "catholic_calendar.py")
combined_mod   = _load("epaper_scribe.providers", "combined_calendar", _PROV / "combined_calendar.py")

get_combined_result  = combined_mod.get_combined_result
build_year_cache     = combined_mod.build_year_cache
AnglicanDay          = combined_mod.AnglicanDay
get_catholic_feasts  = cat_mod.get_catholic_feasts
parse_saint_name         = saint_name_mod.parse_saint_name
render_saints_day_image  = saint_name_mod.render_saints_day_image

# ---------------------------------------------------------------------------
# Inlined helpers from saints_day.py (avoid HA imports)
# ---------------------------------------------------------------------------

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

_ANG_TYPE_LABELS: dict[str, str] = {
    "principal feast":    "Principal Feast",
    "principal holy day": "Principal Holy Day",
    "festival":           "Festival",
    "lesser festival":    "Lesser Festival",
    "commemoration":      "Commemoration",
    "sunday":             "Sunday",
}
_CAT_RANK_LABELS: dict[str, str] = {
    "solemnity":    "Solemnity",
    "feast":        "Feast",
    "memorial":     "Memorial",
    "opt_memorial": "Opt. Memorial",
}
_ANG_RANK_NUM: dict[str, int] = {
    "principal feast": 9, "sunday": 8, "principal holy day": 7,
    "festival": 7, "lesser festival": 6, "commemoration": 5,
}
_CAT_RANK_NUM: dict[str, int] = {
    "solemnity": 9, "feast": 7, "memorial": 6, "opt_memorial": 5,
}


def _get_season_description(season: str | None) -> str:
    if not season:
        return ""
    for key in SEASON_DESCRIPTIONS:
        if key.lower() in (season or "").lower():
            return SEASON_DESCRIPTIONS[key]
    return ""


def _format_week(week: str) -> str:
    if not week:
        return week
    parts = week.strip().split()
    if len(parts) == 2:
        return f"{ORDINALS.get(parts[1], parts[1])} Week of {parts[0]}"
    return week


def _compute_calendar_tag(result, cat_feasts: list, ang_type: str) -> str:
    if result.source == "none" or not result.display_name:
        return ""
    cat_rank_str = ""
    if cat_feasts:
        opts: list[tuple[str, str]] = []
        for f in cat_feasts:
            if "/" in f.name:
                for seg in f.name.split("/"):
                    seg = seg.strip()
                    if seg:
                        opts.append((seg, f.rank))
            else:
                opts.append((f.name, f.rank))
        if result.flag and result.flag_source == "catholic":
            cat_rank_str = next(
                (rank for name, rank in opts if name == result.display_name),
                cat_feasts[0].rank,
            )
        elif opts:
            cat_rank_str = max(opts, key=lambda x: _CAT_RANK_NUM.get(x[1].lower(), 4))[1]

    ang_key = ang_type.lower().strip()
    cat_key = cat_rank_str.lower().strip()

    if result.flag:
        if result.flag_source == "anglican":
            return f"Anglican {_ANG_TYPE_LABELS.get(ang_key, ang_type.title())}".strip()
        if result.flag_source == "catholic":
            return f"Catholic {_CAT_RANK_LABELS.get(cat_key, cat_rank_str.title())}".strip()
        return ""

    a_num = _ANG_RANK_NUM.get(ang_key, 4)
    c_num = _CAT_RANK_NUM.get(cat_key, 4)
    if c_num >= a_num and cat_rank_str:
        return _CAT_RANK_LABELS.get(cat_key, cat_rank_str.title())
    return _ANG_TYPE_LABELS.get(ang_key, "")


# ---------------------------------------------------------------------------
# Year cache
# ---------------------------------------------------------------------------

def _fetch_anglican_year(year: int) -> dict[str, AnglicanDay]:
    from liturgical_calendar.liturgical import liturgical_calendar
    result: dict[str, AnglicanDay] = {}
    d = date(year, 1, 1)
    while d.year == year:
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
        d = date.fromordinal(d.toordinal() + 1)
    return result


def _fetch_catholic_year(year: int) -> dict[str, list]:
    result = {}
    d = date(year, 1, 1)
    while d.year == year:
        feasts = get_catholic_feasts(d)
        if feasts:
            result[d.isoformat()] = feasts
        d = date.fromordinal(d.toordinal() + 1)
    return result


_year_cache: dict[int, object] = {}
_ang_cache:  dict[int, dict]   = {}
_cat_cache:  dict[int, dict]   = {}


def _ensure_year(year: int) -> None:
    if year in _year_cache:
        return
    print(f"  Building year cache for {year}…", flush=True)
    ang = _fetch_anglican_year(year)
    cat = _fetch_catholic_year(year)
    _ang_cache[year]  = ang
    _cat_cache[year]  = cat
    _year_cache[year] = build_year_cache(year, ang, cat)


# ---------------------------------------------------------------------------
# Wikipedia fetching
# ---------------------------------------------------------------------------

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HEADERS = {"User-Agent": "EpaperScribeTest/1.0"}


async def _wiki_one(session, term: str) -> tuple[str, str]:
    import aiohttp
    url = WIKIPEDIA_API + quote(term)
    try:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status != 200:
                return "", ""
            data = await resp.json()
        if data.get("type") == "disambiguation":
            return "", ""
        return data.get("extract", ""), data.get("thumbnail", {}).get("source", "")
    except Exception as exc:
        print(f"    wiki fail {term!r}: {exc}", flush=True)
        return "", ""


async def _wiki_url(session, wiki_url: str) -> tuple[str, str]:
    if "/wiki/" not in wiki_url:
        return "", ""
    return await _wiki_one(session, unquote(wiki_url.split("/wiki/")[-1]))


async def fetch_wikipedia(session, names: list[str], wiki_url: str = "",
                          descriptors: list[str] | None = None) -> tuple[str, str]:
    import re as _re

    def _sing(w: str) -> str:
        skip = {"jesus", "lazarus", "thomas", "status"}
        if w.lower() in skip:
            return w
        return w[:-1] if w.lower().endswith("s") and len(w) > 3 else w

    individuals: list[tuple[str, str]] = []
    for i, name in enumerate(names):
        desc = (descriptors[i] if descriptors and i < len(descriptors) else "") or ""
        if _re.search(r"\band\b", name, _re.IGNORECASE):
            for p in _re.split(r"\s+and\s+", name, flags=_re.IGNORECASE):
                if p.strip():
                    individuals.append((p.strip(), desc))
        else:
            individuals.append((name, desc))

    ind_names = [n for n, _ in individuals]

    def _covers_all(text: str) -> bool:
        tl = text.lower()
        return all(n.split()[0].lower() in tl for n in ind_names)

    if wiki_url:
        ex, img = await _wiki_url(session, wiki_url)
        if ex and (len(ind_names) == 1 or _covers_all(ex)):
            return ex, img

    if not individuals:
        return "", ""

    if len(ind_names) > 1:
        shared_desc = _sing(individuals[0][1].split()[0]) if individuals[0][1] else ""
        joint_base = " and ".join(ind_names)
        queries = []
        if shared_desc:
            queries.append(f"Saints {joint_base}, {shared_desc}")
        queries += [f"Saints {joint_base}", joint_base]
        for q in queries:
            ex, img = await _wiki_one(session, q)
            if ex and _covers_all(ex):
                return ex, img

    sentences: list[str] = []
    image_url = ""
    for name, desc in individuals:
        desc_word = _sing(desc.split()[0]) if desc else ""
        candidates = []
        if desc_word:
            candidates += [f"Saint {name}, {desc_word}", f"Saint {name} the {desc_word}",
                           f"{name} the {desc_word}"]
        candidates += [f"Saint {name}", name]
        ex = im = ""
        for q in candidates:
            ex, im = await _wiki_one(session, q)
            if ex:
                break
        if ex:
            first = ex.split(". ")[0].strip()
            sentences.append(first if first.endswith(".") else first + ".")
        if im and not image_url:
            image_url = im

    return (" ".join(sentences), image_url) if sentences else ("", "")


async def fetch_image(session, url: str) -> bytes | None:
    if not url:
        return None
    try:
        async with session.get(url, headers=HEADERS) as resp:
            return await resp.read() if resp.status == 200 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Render one date to one PNG
# ---------------------------------------------------------------------------

SIZE = (296, 128)


async def render_date(
    session, d: date,
    font_path: str | None,
    name_font_path: str | None,
    out_path: Path,
) -> None:
    _ensure_year(d.year)
    flags   = _year_cache[d.year]
    ang_day = _ang_cache[d.year].get(d.isoformat())
    result  = get_combined_result(d, ang_day, flags)

    parsed = None
    description = ""
    image_bytes = None
    saint_name_str = ""

    if result.source != "none" and result.display_name:
        parsed = parse_saint_name(result.display_name)
        saint_name_str = result.display_name
        names = [s.name for s in parsed.segments] if parsed.segments else [result.display_name]
        descs = [s.descriptor for s in parsed.segments] if parsed.segments else []
        description, image_url = await fetch_wikipedia(session, names, result.wiki_url, descs)
        if image_url:
            image_bytes = await fetch_image(session, image_url)

    season_desc  = _get_season_description(result.season or "")
    ang_type     = result.anglican.type_ if result.anglican else ""
    cat_feasts   = get_catholic_feasts(d)
    calendar_tag = _compute_calendar_tag(result, cat_feasts, ang_type) if saint_name_str else ""

    print(f"    display={result.display_name!r}  source={result.source}  tag={calendar_tag!r}", flush=True)
    desc_preview = (description if saint_name_str else season_desc)[:80]
    print(f"    desc[:80]={desc_preview!r}", flush=True)

    png_bytes = render_saints_day_image(
        size=SIZE,
        parsed=parsed,
        season=result.season or "",
        week=_format_week(result.week) if result.week else "",
        description=description if saint_name_str else season_desc,
        saint_image_bytes=image_bytes,
        font_path=font_path,
        name_font_path=name_font_path,
        calendar_tag=calendar_tag,
    )
    out_path.write_bytes(png_bytes)
    print(f"    → {out_path}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DEFAULT_DATES = [
    "2026-02-14",  # Valentine — Anglican Commemoration, shortish description
    "2026-05-01",  # Joseph the Worker (Catholic) / Philip & James (Anglican)
    "2026-01-25",  # Conversion of Paul — single saint, good portrait
    "2026-11-01",  # All Saints
]


async def main() -> None:
    import aiohttp

    args = sys.argv[1:]
    name_font: str | None = None
    body_font: str | None = None
    date_strs: list[str] = []

    i = 0
    while i < len(args):
        if args[i] == "--name-font" and i + 1 < len(args):
            name_font = args[i + 1]
            i += 2
        elif args[i] == "--body-font" and i + 1 < len(args):
            body_font = args[i + 1]
            i += 2
        else:
            date_strs.append(args[i])
            i += 1

    if not date_strs:
        date_strs = DEFAULT_DATES

    name_label = Path(name_font).stem if name_font else "default"
    body_label = Path(body_font).stem if body_font else "default"
    label = f"name-{name_label}_body-{body_label}"

    dates = []
    for s in date_strs:
        try:
            dates.append(date.fromisoformat(s))
        except ValueError:
            print(f"Skipping invalid date: {s!r}", file=sys.stderr)

    print(f"Name font: {name_font or '(PIL default)'}", flush=True)
    print(f"Body font: {body_font or '(PIL default)'}", flush=True)

    async with aiohttp.ClientSession() as session:
        for d in dates:
            print(f"\n[{d}]", flush=True)
            out = Path(f"/tmp/epaper_scribe_{label}_{d}.png")
            try:
                await render_date(session, d, body_font, name_font, out)
            except Exception as exc:
                import traceback
                print(f"  ERROR: {exc}", flush=True)
                traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
