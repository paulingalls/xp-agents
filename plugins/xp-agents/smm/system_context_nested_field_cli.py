#!/usr/bin/env python3
"""Nested-field-edit commands for system context: stack + branching_strategy.

Extracted from system_context_cli.py to keep that module under the
500-line target. Mirrors the system_context_retire_cli.py +
system_context_edit_cli.py + system_context_caps_cli.py extraction
pattern: re-imported by cli.py and re-exported via __all__ so callers
see no behavior change. The 4 public commands are 1-line dispatchers
over private _edit_nested_field + _get_nested_field helpers — the
parent key + seed dict are the only per-command differences.

Top-level `edit-field` can't reach nested keys (e.g. stack.test_command,
branching_strategy.stage_prompt_dismissed_at), and rewriting the whole
parent object would force callers to re-supply unrelated fields. The
four commands here narrow the edit to one nested field at a time and
let the schema validator catch typos.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store


def _edit_nested_field(args: argparse.Namespace, parent_key: str, seed: dict) -> int:
    """Set or clear one nested field under ``parent_key``.

    Reads the new value from stdin as JSON. ``null`` clears the field.
    Seeds the parent dict if absent so the schema validator accepts
    the result. Validation errors at save time surface on stderr with
    a non-zero return.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1

    raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    parent = data.setdefault(parent_key, dict(seed))
    if value is None:
        parent.pop(args.name, None)
    else:
        parent[args.name] = value

    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _get_nested_field(args: argparse.Namespace, parent_key: str) -> int:
    """Print the value of a nested ``parent_key`` field, or empty string
    if the system_context is missing or the field is unset.

    Exits 0 with empty stdout in the absent case so shell callers can
    plug the value into ``KEY=$(...)`` without exit-code branching.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("")
        return 0
    val = data.get(parent_key, {}).get(args.name)
    print(val if val is not None else "")
    return 0


def cmd_edit_branching_field(args: argparse.Namespace) -> int:
    """Set or clear an optional field nested under branching_strategy.

    Mirrors edit-stack-field: top-level edit-field can't reach nested
    keys, and rewriting the whole branching_strategy via edit-branching
    would force the caller to re-supply stage and any other already-set
    fields. This narrow path edits one nested field at a time and lets
    the schema validator catch typos.

    Seeds branching_strategy with ``{"stage": 0}`` when absent.
    """
    return _edit_nested_field(args, "branching_strategy", {"stage": 0})


def cmd_get_branching_field(args: argparse.Namespace) -> int:
    """Print the value of a nested branching_strategy field.

    Used by xp-kickoff Step 2.4 to read stage_prompt_dismissed_at and
    skip the migration prompt while the dismissal is in effect.
    """
    return _get_nested_field(args, "branching_strategy")


def cmd_get_stack_field(args: argparse.Namespace) -> int:
    """Print the value of a nested stack field.

    Schema-invalid files surface as a load-time ValueError; we let that
    propagate so the user gets a real traceback. The shell wrapper
    `_preload_base.sh:find_test_command` traps that via
    `2>/dev/null || echo ""` so the close-skill preload still emits
    TEST_COMMAND= (empty) — but the failure isn't silenced at the CLI
    layer.

    Used by `_preload_base.sh:find_test_command` to source the project's
    test command for the story-close + free-close auto-merge gate.
    """
    return _get_nested_field(args, "stack")


def cmd_edit_stack_field(args: argparse.Namespace) -> int:
    """Set or clear an optional field nested under stack (e.g. test_command).

    Seeds stack with ``{"languages": []}`` when absent.
    """
    return _edit_nested_field(args, "stack", {"languages": []})
