"""
romcal/bundles.py — Lazy-loading bundle proxy classes for each calendar+locale.

HAND-WRITTEN Python hook. No TypeScript source equivalent.

In TypeScript, each calendar+locale combination ships as a separate npm
package (e.g. ``@romcal/calendar-general-roman``).  In Python there are no
separate packages; this module provides lightweight proxy classes that load the
relevant JSON data on first access.

Usage::

    from romcal import Romcal
    from romcal.bundles import GeneralRoman_En

    romcal = Romcal(localized_calendar=GeneralRoman_En)
    calendar = romcal.generate_calendar(2026)

Adding new calendars:
    1. Verify the calendar JSON exists in ``romcal/data/calendars/<id>.json``.
    2. Verify a matching locale JSON exists in ``romcal/data/locales/<code>.json``.
    3. Add a new subclass of ``_BundleProxy`` below with the appropriate
       ``_calendar_id`` and ``_locale_code`` class attributes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from romcal.types import RomcalBundle
from romcal.utils.objects import _Obj

_DATA = Path(__file__).parent / "data"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _camel_to_snake(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s).lower()


def _to_obj(data: Any) -> Any:
    """Recursively convert plain dicts to _Obj with snake_case keys."""
    if isinstance(data, dict):
        return _Obj({_camel_to_snake(k): _to_obj(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_to_obj(item) for item in data]
    return data


def _build_chain(calendar_id: str, inheritance: dict) -> list[str]:
    """
    Return the list of calendar IDs from most-general ancestor to *calendar_id*
    itself, with duplicates removed.
    """
    parents = inheritance.get(calendar_id, [])
    chain: list[str] = []
    for parent in parents:
        chain.extend(_build_chain(parent, inheritance))
    # Append self and deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for cid in chain + [calendar_id]:
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def _load_bundle(calendar_id: str, locale_code: str) -> RomcalBundle:
    """
    Load and assemble a :class:`RomcalBundle` for *calendar_id* + *locale_code*.

    Inputs are merged from the full inheritance chain (most-general first) with
    ``fromCalendarId`` stamped on each entry so the calendar engine can track
    which calendar each definition originates from.
    """
    with open(_DATA / "calendars" / "_inheritance.json", encoding="utf-8") as fh:
        inheritance: dict = json.load(fh)
    with open(_DATA / "martyrology.json", encoding="utf-8") as fh:
        martyrology: dict = json.load(fh)
    with open(_DATA / "particular_configs.json", encoding="utf-8") as fh:
        particular_configs: dict = json.load(fh)

    # ── Locale data ───────────────────────────────────────────────────────────
    locale_path = _DATA / "locales" / f"{locale_code}.json"
    if not locale_path.exists():
        locale_path = _DATA / "locales" / "en.json"
    with open(locale_path, encoding="utf-8") as fh:
        i18n_raw: dict = json.load(fh)

    i18n_fallback_raw: dict = {}
    if locale_code != "en":
        en_path = _DATA / "locales" / "en.json"
        if en_path.exists():
            with open(en_path, encoding="utf-8") as fh:
                i18n_fallback_raw = json.load(fh)

    # Convert locale dicts to _Obj so config.py can do locale.seasons, locale.id, etc.
    i18n = _to_obj(i18n_raw)
    i18n_fallback = _to_obj(i18n_fallback_raw)

    # ── Merge calendar inputs from inheritance chain ───────────────────────────
    chain = _build_chain(calendar_id, inheritance)
    merged_inputs: dict[str, Any] = {}

    for cal_id in chain:
        cal_file = _DATA / "calendars" / f"{cal_id}.json"
        if not cal_file.exists():
            continue
        with open(cal_file, encoding="utf-8") as fh:
            cal_data: dict = json.load(fh)

        from_id = cal_id.replace("-", "_")
        for entry_id, entry in cal_data.items():
            if isinstance(entry, list):
                stamped = [{**e, "fromCalendarId": from_id} for e in entry]
                merged_inputs[entry_id] = stamped
            else:
                merged_inputs[entry_id] = {**entry, "fromCalendarId": from_id}

    # ── Particular config (snake_case keys) ───────────────────────────────────
    raw_pc = particular_configs.get(calendar_id, {})
    particular_config = _Obj({_camel_to_snake(k): v for k, v in raw_pc.items()})

    calendar_name = calendar_id.replace("-", "_")

    # Wrap martyrology in _Obj so subscript access returns None for missing keys
    # (matching JS semantics: catalog[id] → undefined if missing, not KeyError).
    martyrology_obj = _to_obj(martyrology)

    return RomcalBundle(
        calendar_name=calendar_name,
        particular_config=particular_config,
        inputs=merged_inputs,
        martyrology=martyrology_obj,
        i18n=i18n,
        i18n_fallback=i18n_fallback,
    )


# ── Bundle proxy base class ───────────────────────────────────────────────────

class _BundleProxy:
    """
    Lazy-loading bundle proxy.  Each subclass represents one calendar+locale
    combination.  The JSON data is read from disk only on first access.

    ``engine.py``'s ``_resolve_bundle()`` looks for ``_load_bundle`` on the
    proxy object and calls it with ``(calendar_name, locale_code)``.
    """

    _calendar_id: str         # e.g. "general-roman"  (matches JSON filename)
    _locale_code: str         # e.g. "en"
    _calendar_name: str       # e.g. "general_roman"  (snake_case)
    _bundle: RomcalBundle | None = None

    @classmethod
    def _load_bundle(cls, calendar_name: str, locale_code: str) -> RomcalBundle:
        if cls._bundle is None:
            cls._bundle = _load_bundle(cls._calendar_id, cls._locale_code)
        return cls._bundle


# ── Concrete bundle proxies ───────────────────────────────────────────────────
# Add one class per calendar+locale combination you need.
# The class name convention is: CalendarId_LocaleCode  (CamelCase_UpperCode).
# _calendar_id must match a filename in romcal/data/calendars/ (without .json).
# _locale_code must match a filename in romcal/data/locales/ (without .json).

class GeneralRoman_En(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "en"
    _calendar_name = "general_roman"


class GeneralRoman_Es(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "es"
    _calendar_name = "general_roman"


class GeneralRoman_Fr(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "fr"
    _calendar_name = "general_roman"


class GeneralRoman_De(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "de"
    _calendar_name = "general_roman"


class GeneralRoman_It(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "it"
    _calendar_name = "general_roman"


class GeneralRoman_Pl(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "pl"
    _calendar_name = "general_roman"


class GeneralRoman_Pt(_BundleProxy):
    _calendar_id = "general-roman"
    _locale_code = "pt"
    _calendar_name = "general_roman"


class UnitedStates_En(_BundleProxy):
    _calendar_id = "united-states"
    _locale_code = "en"
    _calendar_name = "united_states"


class England_En(_BundleProxy):
    _calendar_id = "england"
    _locale_code = "en"
    _calendar_name = "england"


class Ireland_En(_BundleProxy):
    _calendar_id = "ireland"
    _locale_code = "en"
    _calendar_name = "ireland"


class France_Fr(_BundleProxy):
    _calendar_id = "france"
    _locale_code = "fr"
    _calendar_name = "france"


class Germany_De(_BundleProxy):
    _calendar_id = "germany"
    _locale_code = "de"
    _calendar_name = "germany"


class Italy_It(_BundleProxy):
    _calendar_id = "italy"
    _locale_code = "it"
    _calendar_name = "italy"


class Poland_Pl(_BundleProxy):
    _calendar_id = "poland"
    _locale_code = "pl"
    _calendar_name = "poland"


class Spain_Es(_BundleProxy):
    _calendar_id = "spain"
    _locale_code = "es"
    _calendar_name = "spain"


class Canada_En(_BundleProxy):
    _calendar_id = "canada"
    _locale_code = "en"
    _calendar_name = "canada"


class Australia_En(_BundleProxy):
    _calendar_id = "australia"
    _locale_code = "en"
    _calendar_name = "australia"
