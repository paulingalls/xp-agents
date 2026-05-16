#!/usr/bin/env python3
"""Edit-* CLI handlers for capped lists in system_context.json.

Extracted from system_context_cli.py per the split-shim convention.
Re-exported via cli.py's top-of-file shim so callers continue to
import from system_context_cli.

Each edit-* command patches one entry in a capped list and emits a
STATUS_ACTION_EDIT_* event for traceability. Patch is a JSON object
from stdin merged into the existing entry; `null` value clears a key
(mirroring edit-stack-field). For conventions (bare strings), stdin
is a JSON-encoded replacement string.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import _common
import system_context_store as store
from event_metadata import (
    STATUS_ACTION_EDIT_ACCEPTANCE_SURFACE,
    STATUS_ACTION_EDIT_CONVENTION,
    STATUS_ACTION_EDIT_MODULE,
    STATUS_ACTION_EDIT_PRINCIPLE,
    STATUS_ACTION_EDIT_PROJECT_SPECIFIC,
)
from system_context_retire_cli import resolve_convention_index

_EDIT_ACTIONS: dict[str, str] = {
    "principle": STATUS_ACTION_EDIT_PRINCIPLE,
    "module": STATUS_ACTION_EDIT_MODULE,
    "convention": STATUS_ACTION_EDIT_CONVENTION,
    "project_specific": STATUS_ACTION_EDIT_PROJECT_SPECIFIC,
    "acceptance_surface": STATUS_ACTION_EDIT_ACCEPTANCE_SURFACE,
}


def _emit_edit_event(
    smm_dir: Path, kind: str, identifier: str, patched_keys: list[str]
) -> None:
    """Append a status event recording the edit-* action."""
    event = _common.make_event(
        "status",
        "system-context-cli",
        f"edited {kind} {identifier}",
        working_on=[],
        metadata={
            "action": _EDIT_ACTIONS[kind],
            "kind": kind,
            "identifier": identifier,
            "patched_keys": patched_keys,
        },
    )
    _common.append_safe(smm_dir, event)


def _apply_patch(entry: dict, patch: dict) -> list[str]:
    """Merge `patch` into `entry` in-place. `null` value pops a key.
    Returns the list of keys actually changed (added, replaced, or
    cleared); a no-op set (patch matches current state) returns []."""
    changed: list[str] = []
    for key, value in patch.items():
        if value is None:
            if key in entry:
                del entry[key]
                changed.append(key)
        else:
            if entry.get(key) != value:
                entry[key] = value
                changed.append(key)
    return changed


def _parse_patch_dict() -> dict | None:
    """Read JSON from stdin and return a dict patch, or None on error
    (with error printed to stderr)."""
    raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        return None
    if not isinstance(value, dict):
        print(
            f"Patch must be a JSON object; got {type(value).__name__}",
            file=sys.stderr,
        )
        return None
    return value


def _cmd_edit_by_key(
    args: argparse.Namespace, field: str, key_field: str, kind: str
) -> int:
    """Generic edit-by-key path for object-shaped capped lists.

    Loads, looks up by `entry[key_field] == args.identifier`, parses a
    JSON patch from stdin, merges, saves. No-op patches (matches current
    state) short-circuit without writing or emitting an event.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get(field, [])
    for entry in bucket:
        if entry.get(key_field) == args.identifier:
            patch = _parse_patch_dict()
            if patch is None:
                return 1
            changed = _apply_patch(entry, patch)
            if not changed:
                return 0
            try:
                store.save_system_context(args.smm_dir, data)
            except ValueError as exc:
                print(f"Validation error: {exc}", file=sys.stderr)
                return 1
            _emit_edit_event(args.smm_dir, kind, args.identifier, changed)
            return 0
    print(
        f"{field}[{key_field}={args.identifier!r}] not found",
        file=sys.stderr,
    )
    return 1


def cmd_edit_principle(args: argparse.Namespace) -> int:
    return _cmd_edit_by_key(args, "principles", "topic", "principle")


def cmd_edit_module(args: argparse.Namespace) -> int:
    return _cmd_edit_by_key(args, "modules", "name", "module")


def cmd_edit_project_specific(args: argparse.Namespace) -> int:
    return _cmd_edit_by_key(args, "project_specific", "name", "project_specific")


def cmd_edit_acceptance_surface(args: argparse.Namespace) -> int:
    return _cmd_edit_by_key(args, "acceptance_surfaces", "name", "acceptance_surface")


def cmd_edit_convention(args: argparse.Namespace) -> int:
    """Conventions are bare strings; stdin is a JSON-encoded replacement
    string. Lookup mirrors retire-convention (index OR substring with
    ambiguity rejection)."""
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get("conventions", [])
    idx = resolve_convention_index(bucket, args.identifier)
    if idx is None:
        return 1

    raw = sys.stdin.read()
    try:
        new_text = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if not isinstance(new_text, str):
        print(
            f"Convention replacement must be a JSON string; "
            f"got {type(new_text).__name__}",
            file=sys.stderr,
        )
        return 1

    resolved_original = bucket[idx]
    if new_text == resolved_original:
        return 0
    bucket[idx] = new_text
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    _emit_edit_event(args.smm_dir, "convention", resolved_original, [])
    return 0
