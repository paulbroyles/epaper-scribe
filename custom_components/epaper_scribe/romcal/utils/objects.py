"""
romcal/utils/objects.py — Python-specific dict wrapper with attribute access.

HAND-WRITTEN Python hook. No TypeScript source equivalent.

TypeScript object literals accessed as ``obj.key`` translate to Python as
``_Obj({"key": val}).key``.  _Obj also supports the dict **-unpacking
protocol so ``{**obj, "new_key": val}`` works transparently.

IMPORTANT: always use ``key in obj`` (not ``hasattr``) to test whether a key
is present.  ``__getattr__`` returns ``None`` for missing keys, so
``hasattr(obj, "anything")`` always returns True.
"""
from __future__ import annotations


class _Obj:
    """
    Dict wrapper with attribute-style access; missing keys return ``None``.

    Implements the full mapping protocol so ``**obj`` unpacking works in
    dict literals, e.g. ``{**some_obj, "extra": val}``.
    """

    __slots__ = ("_d",)

    def __init__(self, d: dict | None = None) -> None:
        object.__setattr__(self, "_d", d if d is not None else {})

    # ── Attribute access ───────────────────────────────────────────────────────

    def __getattr__(self, name: str):
        return object.__getattribute__(self, "_d").get(name)

    def __setattr__(self, name: str, value) -> None:
        object.__getattribute__(self, "_d")[name] = value

    def __delattr__(self, name: str) -> None:
        d = object.__getattribute__(self, "_d")
        d.pop(name, None)

    # ── Mapping protocol (for `in` checks and ** unpacking) ────────────────────

    def __contains__(self, key: str) -> bool:
        return key in object.__getattribute__(self, "_d")

    def __getitem__(self, key: str):
        # Match JS semantics: missing key → None (not KeyError), same as __getattr__.
        return object.__getattribute__(self, "_d").get(key)

    def __setitem__(self, key: str, value) -> None:
        object.__getattribute__(self, "_d")[key] = value

    def __delitem__(self, key: str) -> None:
        del object.__getattribute__(self, "_d")[key]

    def keys(self):
        return object.__getattribute__(self, "_d").keys()

    def values(self):
        return object.__getattribute__(self, "_d").values()

    def items(self):
        return object.__getattribute__(self, "_d").items()

    def get(self, key: str, default=None):
        return object.__getattribute__(self, "_d").get(key, default)

    # ── Iteration and length ───────────────────────────────────────────────────

    def __iter__(self):
        return iter(object.__getattribute__(self, "_d"))

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_d"))

    # ── Truth value ───────────────────────────────────────────────────────────

    def __bool__(self) -> bool:
        return bool(object.__getattribute__(self, "_d"))

    # ── Representation ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"_Obj({object.__getattribute__(self, '_d')!r})"
