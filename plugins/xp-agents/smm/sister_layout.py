#!/usr/bin/env python3
"""Resolve the configured sister-test layout from system_context.

Extracted from sprint_save.py, which sat at its file-size band ceiling and
could not take a new parameter without breaching it. One responsibility:
turn `system_context.test_layout` (JSON) into a `sister_tests.TestLayout`, or
None when no usable layout is configured. Never writes; the soft-warn that
fires on None stays with the caller, because whether a missing layout deserves
a warning is the caller's policy, not this module's.

sprint_save re-exports both names so `sprint_save._resolve_layout` keeps
working for the existing sister-test suites.
"""

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import sister_tests  # noqa: E402  # pyright: ignore[reportMissingImports]
import system_context_store  # noqa: E402


def _coerce_overrides(raw: object) -> tuple["sister_tests.TestLayoutRule", ...]:
    """Coerce JSON list-of-dicts to tuple-of-TestLayoutRule. Round-trips
    skip_basenames/skip_suffixes/source_excludes from JSON list to tuple.
    Silently drops malformed entries — schema validator is the source of
    truth; this is defensive."""
    if not isinstance(raw, list):
        return ()
    out: list[sister_tests.TestLayoutRule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                sister_tests.TestLayoutRule(
                    source_pattern=entry["source_pattern"],
                    stem_extractor=entry["stem_extractor"],
                    test_glob=entry["test_glob"],
                    skip_basenames=tuple(entry.get("skip_basenames", ())),
                    skip_suffixes=tuple(entry.get("skip_suffixes", ())),
                    source_excludes=tuple(entry.get("source_excludes", ())),
                )
            )
        except (KeyError, TypeError):
            continue
    return tuple(out)


def _resolve_layout(smm_dir: Path) -> "sister_tests.TestLayout | None":
    """Load system_context.test_layout and construct a TestLayout. Returns
    None when test_layout is absent, convention is 'unknown', system_context
    is missing/unreadable, OR the layout resolves to no rules and no
    overrides (a degenerate "custom" with empty overrides). Never writes
    events.

    Returning None for the degenerate-custom case ensures the soft-warn
    path fires once instead of silently no-op'ing every save."""
    try:
        sc = system_context_store.load_system_context(smm_dir)
    except (OSError, ValueError):
        return None
    if sc is None:
        return None
    layout_data = sc.get("test_layout")
    if not isinstance(layout_data, dict):
        return None
    convention = layout_data.get("convention")
    if not isinstance(convention, str) or convention == "unknown":
        return None
    if convention == "custom":
        rules: tuple[sister_tests.TestLayoutRule, ...] = ()
    else:
        builtin = sister_tests.BUILTIN_LAYOUTS.get(convention)
        if builtin is None:
            return None  # schema validator should catch this earlier
        rules = builtin.rules
    overrides = _coerce_overrides(layout_data.get("overrides", []))
    if not rules and not overrides:
        # Degenerate layout (convention='custom' with empty/malformed
        # overrides) — discovery would iterate zero rules and return zero
        # sisters on every save. Treat as "no layout configured" so the
        # soft-warn path surfaces it.
        return None
    return sister_tests.TestLayout(
        convention=convention, rules=rules, overrides=overrides
    )
