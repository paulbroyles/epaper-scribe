"""Standalone async test script for saints_day.py logic.

Tests:
  Part A: _extract_infobox_field directly (function copied inline)
  Part B: Disambiguation resolution logic replicated standalone
"""

import asyncio
import re
import calendar
from urllib.parse import quote

import aiohttp

WIKIPEDIA_MW_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REST_API = "https://en.wikipedia.org/api/rest_v1/page/summary"
HEADERS = {"User-Agent": "EpaperScribeTest/1.0 test-script"}


# ---------------------------------------------------------------------------
# Copy of _extract_infobox_field from saints_day.py (lines 1365-1394)
# ---------------------------------------------------------------------------

def _extract_infobox_field(wikitext: str, field_name: str) -> str:
    """Extract a named field's raw value from a Wikipedia infobox."""
    pattern = re.compile(
        r'^\|\s*' + re.escape(field_name) + r'\s*=',
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(wikitext)
    if not m:
        return ""
    start = wikitext.rfind("\n", 0, m.start()) + 1
    segment = wikitext[start:]
    lines = segment.split("\n", 5)[:5]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: fetch wikitext for a title
# ---------------------------------------------------------------------------

async def fetch_wikitext(session: aiohttp.ClientSession, title: str) -> str:
    url = (
        WIKIPEDIA_MW_API
        + "?action=query&prop=revisions&rvprop=content&rvslots=main"
        + "&format=json&redirects=1&titles=" + quote(title)
    )
    async with session.get(url, headers=HEADERS) as resp:
        resp.raise_for_status()
        data = await resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        rev = (page.get("revisions") or [{}])[0]
        return (
            rev.get("slots", {}).get("main", {}).get("*", "")
            or rev.get("*", "")
        )
    return ""


# ---------------------------------------------------------------------------
# Helper: fetch REST summary text
# ---------------------------------------------------------------------------

async def fetch_summary(session: aiohttp.ClientSession, title: str) -> str:
    url = f"{WIKIPEDIA_REST_API}/{quote(title)}"
    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            return ""
        data = await resp.json()
    return data.get("extract", "")


# ---------------------------------------------------------------------------
# Part A
# ---------------------------------------------------------------------------

async def part_a(session: aiohttp.ClientSession) -> None:
    print("=" * 70)
    print("PART A — _extract_infobox_field tests")
    print("=" * 70)

    # ---- Pancras of Rome ------------------------------------------------
    print("\n--- Pancras of Rome ---")
    wikitext = await fetch_wikitext(session, "Pancras of Rome")
    await asyncio.sleep(0.5)

    feast_val = _extract_infobox_field(wikitext, "feast_day")
    death_val = _extract_infobox_field(wikitext, "death_date")

    print(f"feast_day  field (5-line window):\n{feast_val!r}")
    print(f"death_date field (5-line window):\n{death_val!r}")

    # Assertions
    feast_lower = feast_val.lower()
    assert "12 may" in feast_lower or "may 12" in feast_lower, (
        f"FAIL: feast_day for Pancras of Rome should contain '12 may' or 'may 12', got: {feast_val!r}"
    )
    print("PASS: feast_day contains expected date (12 may / may 12)")

    assert "303" in death_val, (
        f"FAIL: death_date for Pancras of Rome should contain '303', got: {death_val!r}"
    )
    print("PASS: death_date contains '303'")

    # ---- George of Lydda ------------------------------------------------
    print("\n--- George of Lydda ---")
    wikitext_g = await fetch_wikitext(session, "George of Lydda")
    await asyncio.sleep(0.5)

    feast_val_g = _extract_infobox_field(wikitext_g, "feast_day")
    death_val_g = _extract_infobox_field(wikitext_g, "death_date")

    print(f"feast_day  field (5-line window):\n{feast_val_g!r}")
    print(f"death_date field (5-line window):\n{death_val_g!r}")

    assert "303" in death_val_g, (
        f"FAIL: death_date for George of Lydda should contain '303', got: {death_val_g!r}"
    )
    print("PASS: death_date contains '303'")

    april_present = "april" in feast_val_g.lower()
    print(f"Note: 'april' present in George feast_day 5-line window: {april_present}")


# ---------------------------------------------------------------------------
# Part B — replicated disambiguation logic
# ---------------------------------------------------------------------------

async def resolve_from_disambiguation(
    session: aiohttp.ClientSession,
    dis_title: str,
    first_name: str,
    hint_year: int | None,
    hint_mmdd: str,
) -> tuple[str, float]:
    """Replicate _resolve_from_disambiguation logic standalone."""
    fn_lower = first_name.lower()
    year_str = str(hint_year) if hint_year is not None else ""

    # Build feast-date match patterns
    feast_patterns: list[str] = []
    if hint_mmdd:
        try:
            month_num = int(hint_mmdd.split("-")[0])
            day_num   = int(hint_mmdd.split("-")[1])
            month_name = calendar.month_name[month_num].lower()
            feast_patterns = [
                f"{month_name} {day_num}",
                f"{day_num} {month_name}",
            ]
        except (ValueError, IndexError):
            pass
    print(f"\nFeast patterns: {feast_patterns}")
    print(f"Year string:    {year_str!r}")

    # 1. Fetch disambiguation page wikitext
    print(f"\nFetching wikitext for disambiguation page: {dis_title!r} ...")
    dis_wikitext = await fetch_wikitext(session, dis_title)
    await asyncio.sleep(0.5)

    if not dis_wikitext:
        print("ERROR: could not fetch disambiguation wikitext")
        return "", -1

    # 2. Parse wikitext — section-filtered candidate links
    PERSON_KEYWORDS = {
        "people", "person", "persons", "saints", "saint",
        "religious", "clergy", "christian", "christians",
        "martyr", "martyrs", "biography", "biographies",
    }

    in_person_section = False
    has_person_sections = False
    person_links: list[str] = []
    all_name_links: list[str] = []
    found_person_section_names: list[str] = []

    for line in dis_wikitext.split("\n"):
        hdr_m = re.match(r'^={2,}\s*(.+?)\s*={2,}\s*$', line)
        if hdr_m:
            words = set(hdr_m.group(1).lower().split())
            in_person_section = bool(words & PERSON_KEYWORDS)
            if in_person_section:
                has_person_sections = True
                found_person_section_names.append(hdr_m.group(1))
            continue
        for lm in re.finditer(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]', line):
            title = lm.group(1).strip()
            if fn_lower in title.lower():
                all_name_links.append(title)
                if in_person_section:
                    person_links.append(title)

    print(f"\nPerson-type sections found: {found_person_section_names}")
    print(f"has_person_sections: {has_person_sections}")
    print(f"person_links: {person_links}")
    print(f"all_name_links: {all_name_links}")

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

    print(f"\nFinal candidate list (after dedup): {candidates}")

    if not candidates:
        print("No candidates found matching first_name.")
        return "", -1

    # 3. Score each candidate
    best_title = ""
    best_score = -1

    print("\n" + "-" * 60)
    print("SCORING CANDIDATES")
    print("-" * 60)

    for title in candidates:
        infobox_score = 0
        death_val = ""
        feast_val = ""

        # 3a. Fetch candidate wikitext for infobox scoring
        print(f"\n  Candidate: {title!r}")
        try:
            art_wikitext = await fetch_wikitext(session, title)
            await asyncio.sleep(0.5)
            if art_wikitext:
                death_val = _extract_infobox_field(art_wikitext, "death_date")
                feast_val = _extract_infobox_field(art_wikitext, "feast_day")
                print(f"    death_date: {death_val!r}")
                print(f"    feast_day:  {feast_val!r}")
                if year_str and death_val and year_str in death_val:
                    infobox_score += 20
                    print(f"    +20 (death year {year_str!r} in infobox death_date)")
                if feast_patterns and feast_val:
                    fv_lower = feast_val.lower()
                    if any(p in fv_lower for p in feast_patterns):
                        infobox_score += 15
                        print(f"    +15 (feast date matches in infobox feast_day)")
        except Exception as exc:
            print(f"    ERROR fetching wikitext: {exc}")

        # 3b. Fetch REST summary
        text_score = 0
        try:
            summary_text = await fetch_summary(session, title)
            await asyncio.sleep(0.5)
            if summary_text:
                text_lower = summary_text.lower()
                if year_str and year_str in summary_text:
                    text_score += 5
                    print(f"    +5 (year {year_str!r} in summary text)")
                if feast_patterns and any(p in text_lower for p in feast_patterns):
                    text_score += 3
                    print(f"    +3 (feast date in summary text)")
            else:
                print(f"    (no summary text fetched)")
        except Exception as exc:
            print(f"    ERROR fetching summary: {exc}")

        score = infobox_score + text_score
        print(f"    TOTAL SCORE: infobox={infobox_score} text={text_score} => {score}")

        if score > best_score:
            best_score = score
            best_title = title

    print("\n" + "=" * 60)
    if best_score > 0:
        print(f"WINNER: {best_title!r} with score {best_score}")
    else:
        print("No candidate had a positive score.")
    print("=" * 60)

    return best_title, best_score


async def part_b(session: aiohttp.ClientSession) -> None:
    print("\n" + "=" * 70)
    print("PART B — Disambiguation flow for 'St. Pancras'")
    print("=" * 70)

    winner, score = await resolve_from_disambiguation(
        session,
        dis_title="St. Pancras",
        first_name="Pancras",
        hint_year=303,
        hint_mmdd="05-12",
    )

    assert winner == "Pancras of Rome", (
        f"FAIL: Expected winner 'Pancras of Rome', got {winner!r}"
    )
    assert score > 0, f"FAIL: Expected score > 0, got {score}"
    print("\nPASS: 'Pancras of Rome' won with score > 0")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    async with aiohttp.ClientSession() as session:
        await part_a(session)
        await part_b(session)
    print("\nAll tests completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
