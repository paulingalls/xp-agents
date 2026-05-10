#!/usr/bin/env python3
"""Curated install-map lookup for /xp-scaffold-acceptance Step 2.

Loads ``known_installs.json`` from this directory and exposes
``load_known_install(tool: str) -> dict | None`` for the skill (called
via Bash) and tests. Returns the per-tool entry as a dict (with keys
``install_cmds``, ``verify_identity_cmd``, ``expected_version_pattern``)
when the tool is in the curated map, else None — caller falls back to
the WebSearch flow.

Why a dedicated module: the JSON read is one-line, but the skill needs
a stable CLI entry point AND tests need an importable function. Living
in scaffold_cli.py would push that file over its 500-line budget; living
in scaffold_plan.py would couple the pure plan dataclass to disk I/O.
A standalone single-purpose module keeps both clean.

Stdlib-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_KNOWN_INSTALLS_PATH = Path(__file__).resolve().parent / "known_installs.json"


def load_known_install(tool: str) -> dict | None:
    """Return the curated install entry for ``tool`` or None.

    None when ``tool`` is empty, when the JSON file is missing or
    malformed (defensive — a broken map should not block the scaffold
    flow), or when ``tool`` has no curated entry. Keys starting with
    ``_`` (e.g., the ``_README`` doc string) are not lookup-eligible.
    """
    if not tool or tool.startswith("_"):
        return None
    try:
        data = json.loads(_KNOWN_INSTALLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get(tool)
    if not isinstance(entry, dict):
        return None
    return entry


def _cmd_lookup(args: list[str]) -> int:
    """CLI entry: print the entry as JSON to stdout, exit 0; else exit 2."""
    if len(args) != 1:
        print("usage: known_installs.py <tool>", file=sys.stderr)
        return 1
    entry = load_known_install(args[0])
    if entry is None:
        return 2
    print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    sys.exit(_cmd_lookup(sys.argv[1:]))
