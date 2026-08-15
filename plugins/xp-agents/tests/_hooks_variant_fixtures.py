#!/usr/bin/env python3
"""Shared locations and one flatten helper for the hooks-variant pin suites.

Deliberately holds NO expectations. The three suites that import it each spell
their own expected sets literally, because a pin whose oracle lives beside the
thing under test asserts only that the two agree — the reason
`test_hooks_variant_subtraction.py` spells `RECOGNISED`/`UNRECOGNISED` itself
rather than importing `hooks_emit`'s tables, and the reason the declared
additions are spelled in exactly one suite.

What belongs here is what has no expectation in it at all: where the two
manifests live, and how to walk them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

_HOOKS_DIR = _PLUGIN_ROOT / "hooks"
_SOURCE = _HOOKS_DIR / "hooks.json"
_CODEX = _HOOKS_DIR / "hooks.codex.json"


def _all_hook_objects(manifest: dict) -> list[tuple[str, dict]]:
    """Every (event, hook-object) pair in a manifest, flattened."""
    return [
        (event, hook)
        for event, entries in manifest["hooks"].items()
        for entry in entries
        for hook in entry.get("hooks", [])
    ]
