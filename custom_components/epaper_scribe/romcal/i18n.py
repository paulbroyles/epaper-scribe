"""
romcal/i18n.py — Python replacement for the i18next npm package.

HAND-WRITTEN Python hook: there is no TypeScript source to translate from.
i18next is an external npm package; this module implements the subset of its
API that romcal uses.

Interface used by romcal:
    i18n = I18n({})
    i18n.add_resource_bundle(locale_id, namespace, data_dict)
    translated = i18n.t("namespace:dotted.key.path", options_dict)

Translation string format (i18next conventions):
    {{var}}             — interpolated from options dict
    $t(key, modifier)   — cross-reference to another key; modifier may be
                          "capitalize" to title-case the resolved value
"""
from __future__ import annotations

import re
from typing import Any


class I18n:
    """
    Minimal i18next replacement.

    Store: {locale_id: {namespace: nested_dict_of_strings}}
    Active locale is set to the first non-"dev" locale registered via
    add_resource_bundle().  "en" is always tried as a final fallback.
    """

    def __init__(self, options: dict | None = None) -> None:
        # {locale_id: {namespace: dict}}
        self._store: dict[str, dict[str, Any]] = {}
        self._locale: str = "dev"

    # ── Resource registration ─────────────────────────────────────────────────

    def add_resource_bundle(
        self,
        locale_id: str,
        namespace: str,
        data: Any,
    ) -> None:
        """Register translation data for a locale + namespace."""
        if locale_id not in self._store:
            self._store[locale_id] = {}
        # Materialise _Obj or other mapping proxies to a plain dict so we can
        # navigate with plain dict lookups later.
        self._store[locale_id][namespace] = _to_plain(data)
        # Track the active locale (first non-dev locale wins).
        if locale_id not in ("dev",) and self._locale == "dev":
            self._locale = locale_id

    # ── Translation ───────────────────────────────────────────────────────────

    def t(self, key: str, options: Any = None) -> str | None:
        """
        Translate *key* with optional *options* dict for interpolation.

        key format: ``"namespace:dotted.path"``
        Returns None if the key cannot be found.
        """
        if not key or ":" not in key:
            return None

        namespace, rest = key.split(":", 1)
        raw = self._lookup(namespace, rest)
        if raw is None:
            return None

        # Flatten options to a plain dict (accepts _Obj or plain dict or None).
        opts: dict = {}
        if options is not None:
            if hasattr(options, "items"):
                opts = {k: v for k, v in options.items()}
            elif isinstance(options, dict):
                opts = options

        # Resolve the value: first expand {{vars}}, then resolve $t() refs.
        return self._resolve(raw, opts)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _lookup(self, namespace: str, path: str) -> str | None:
        """
        Navigate *path* (dot-separated) inside *namespace*, trying the active
        locale first then "en" as a fallback.
        """
        for loc in _unique((self._locale, "en")):
            ns_data = self._store.get(loc, {}).get(namespace)
            if ns_data is None:
                continue
            val = _dot_get(ns_data, path)
            if val is not None:
                return val
        return None

    def _resolve(self, template: str, opts: dict) -> str:
        """
        Fully resolve a raw translation string:
        1. Expand ``{{var}}`` placeholders from *opts*.
        2. Resolve ``$t(key, modifier)`` cross-references (may be nested).
        """
        # Resolve $t(...) cross-references first so that the referenced
        # string is substituted before {{var}} expansion.
        result = _RE_REF.sub(lambda m: self._resolve_ref(m, opts), template)
        # Then expand remaining {{var}} placeholders.
        result = _RE_VAR.sub(lambda m: _sub_var(m, opts), result)
        return result

    def _resolve_ref(self, m: re.Match, opts: dict) -> str:
        """
        Resolve a single ``$t(key, modifier)`` match.
        The key inside may itself contain ``{{var}}`` that are expanded first.
        """
        key_raw = m.group(1).strip()
        modifier = (m.group(2) or "").strip()

        # Expand {{var}} inside the key string (e.g. $t(ordinals:{{week}})).
        key_resolved = _RE_VAR.sub(lambda mv: _sub_var(mv, opts), key_raw)

        val = self.t(key_resolved)
        if val is None:
            return m.group(0)  # leave unresolved reference as-is

        if modifier == "capitalize":
            val = val[:1].upper() + val[1:] if val else val

        return val


# ── Module-level helpers ──────────────────────────────────────────────────────

_RE_VAR = re.compile(r"\{\{(\w+)\}\}")
_RE_REF = re.compile(r"\$t\(([^,)]+)(?:,\s*([^)]+))?\)")


def _to_plain(data: Any) -> Any:
    """Recursively convert _Obj / mapping proxies to plain Python dicts."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return {k: _to_plain(v) for k, v in data.items()}
    if hasattr(data, "items"):
        return {k: _to_plain(v) for k, v in data.items()}
    return data


def _dot_get(data: Any, path: str) -> str | None:
    """Navigate a dot-separated *path* through nested dicts; return None if missing."""
    parts = path.split(".")
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif hasattr(cur, "get"):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur if isinstance(cur, str) else None


def _sub_var(m: re.Match, opts: dict) -> str:
    """Replace a ``{{var}}`` match with its value from *opts*."""
    key = m.group(1).strip()
    val = opts.get(key)
    return str(val) if val is not None else m.group(0)


def _unique(seq):
    """Yield items from *seq* without duplicates, preserving order."""
    seen: set = set()
    for item in seq:
        if item not in seen:
            seen.add(item)
            yield item
