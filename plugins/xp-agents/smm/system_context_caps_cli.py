#!/usr/bin/env python3
"""Cap-enforcement helpers for capped-list curation.

Extracted from system_context_cli.py to keep that module under the
500-line target. Mirrors the system_context_retire_cli.py +
system_context_edit_cli.py extraction pattern: re-imported by cli.py
and re-exported via __all__ so callers see no behavior change.

The cap table maps each gated list field to (soft, hard, retire-subcmd).
Soft cap warns on stderr after a successful append; hard cap refuses
the append with a retire-first hint and exits non-zero.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store
from system_context_schema import (
    ACCEPTANCE_SURFACES_HARD_CAP,
    ACCEPTANCE_SURFACES_SOFT_CAP,
    CONVENTIONS_HARD_CAP,
    CONVENTIONS_SOFT_CAP,
    MODULES_HARD_CAP,
    MODULES_SOFT_CAP,
    PRINCIPLES_HARD_CAP,
    PRINCIPLES_SOFT_CAP,
    PROJECT_SPECIFIC_HARD_CAP,
    PROJECT_SPECIFIC_SOFT_CAP,
)

# (soft, hard, retire-subcmd-name) per gated list field. Retire-subcmd
# names are paired with the matching retire-* CLI subcommand so the
# "run retire-<kind> first" hint at hard cap resolves to a real command.
_COUNT_CAP_TABLE: dict[str, tuple[int, int, str]] = {
    "modules": (MODULES_SOFT_CAP, MODULES_HARD_CAP, "retire-module"),
    "conventions": (CONVENTIONS_SOFT_CAP, CONVENTIONS_HARD_CAP, "retire-convention"),
    "principles": (PRINCIPLES_SOFT_CAP, PRINCIPLES_HARD_CAP, "retire-principle"),
    "project_specific": (
        PROJECT_SPECIFIC_SOFT_CAP,
        PROJECT_SPECIFIC_HARD_CAP,
        "retire-project-specific",
    ),
    "acceptance_surfaces": (
        ACCEPTANCE_SURFACES_SOFT_CAP,
        ACCEPTANCE_SURFACES_HARD_CAP,
        "retire-acceptance-surface",
    ),
}


def cmd_append_to_list(
    args: argparse.Namespace, field: str, *, create_if_missing: bool = False
) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        item = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    caps = _COUNT_CAP_TABLE.get(field)
    bucket = data.setdefault(field, []) if create_if_missing else data[field]

    if caps is not None:
        _, hard, retire_cmd = caps
        if len(bucket) >= hard:
            print(
                f"{field} hard cap reached ({len(bucket)}/{hard}); "
                f"run {retire_cmd} first",
                file=sys.stderr,
            )
            return 1

    bucket.append(item)
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1

    if caps is not None:
        soft, hard, _ = caps
        if len(bucket) >= soft:
            print(
                f"{field} approaching cap ({len(bucket)}/{hard})",
                file=sys.stderr,
            )

    return 0
