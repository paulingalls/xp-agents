#!/usr/bin/env python3
"""Retire-* CLI handlers for capped lists in system_context.json.

Extracted from system_context_cli.py per the split-shim convention
(plugin code targets ≤500 lines/file). Re-exported via cli.py's
top-of-file shim so callers continue to import from system_context_cli.

Each retire-* command hard-deletes one entry from a capped list and
emits a STATUS_ACTION_RETIRE_* event so curation is traceable in
events.jsonl. Provenance survives in the original `decision` event.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import _common
import system_context_store as store
from event_metadata import (
    STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE,
    STATUS_ACTION_RETIRE_CONVENTION,
    STATUS_ACTION_RETIRE_MODULE,
    STATUS_ACTION_RETIRE_PRINCIPLE,
    STATUS_ACTION_RETIRE_PROJECT_SPECIFIC,
)

# Map kind → STATUS_ACTION constant for retire-* status event emission.
# The CLI is a non-hook producer; constants live in event_metadata.py +
# tests/hooks/test_action_vocabulary_smoke.py:_NON_HOOK_PRODUCERS.
_RETIRE_ACTIONS: dict[str, str] = {
    "principle": STATUS_ACTION_RETIRE_PRINCIPLE,
    "module": STATUS_ACTION_RETIRE_MODULE,
    "convention": STATUS_ACTION_RETIRE_CONVENTION,
    "project_specific": STATUS_ACTION_RETIRE_PROJECT_SPECIFIC,
    "acceptance_surface": STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE,
}


def resolve_convention_index(bucket: list, identifier: str) -> int | None:
    """Resolve a convention identifier to a bucket index.

    `identifier` is either a digit string (direct index) or a substring
    (must match exactly one entry). Prints an error to stderr and
    returns None on miss / ambiguity / out-of-range. Shared by
    retire-convention + edit-convention.
    """
    if identifier.isdigit():
        idx = int(identifier)
        if idx < 0 or idx >= len(bucket):
            print(
                f"conventions[{idx}] out of range (have {len(bucket)} entries)",
                file=sys.stderr,
            )
            return None
        return idx
    matches = [i for i, c in enumerate(bucket) if identifier in c]
    if not matches:
        print(
            f"conventions: no match for substring {identifier!r}",
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        preview = "; ".join(bucket[i] for i in matches)
        print(
            f"conventions: ambiguous substring {identifier!r} "
            f"({len(matches)} matches): {preview}",
            file=sys.stderr,
        )
        return None
    return matches[0]


def _emit_retire_event(smm_dir: Path, kind: str, identifier: str) -> None:
    """Append a status event recording the retire-* action."""
    event = _common.make_event(
        "status",
        "system-context-cli",
        f"retired {kind} {identifier}",
        working_on=[],
        metadata={
            "action": _RETIRE_ACTIONS[kind],
            "kind": kind,
            "identifier": identifier,
        },
    )
    _common.append_safe(smm_dir, event)


def _cmd_retire_by_key(
    args: argparse.Namespace, field: str, key_field: str, kind: str
) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get(field, [])
    for i, entry in enumerate(bucket):
        if entry.get(key_field) == args.identifier:
            del bucket[i]
            try:
                store.save_system_context(args.smm_dir, data)
            except ValueError as exc:
                print(f"Validation error: {exc}", file=sys.stderr)
                return 1
            _emit_retire_event(args.smm_dir, kind, args.identifier)
            return 0
    print(
        f"{field}[{key_field}={args.identifier!r}] not found",
        file=sys.stderr,
    )
    return 1


def cmd_retire_principle(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "principles", "topic", "principle")


def cmd_retire_module(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "modules", "name", "module")


def cmd_retire_project_specific(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "project_specific", "name", "project_specific")


def cmd_retire_acceptance_surface(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "acceptance_surfaces", "name", "acceptance_surface")


def cmd_retire_convention(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get("conventions", [])
    idx = resolve_convention_index(bucket, args.identifier)
    if idx is None:
        return 1
    resolved = bucket[idx]

    del bucket[idx]
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    _emit_retire_event(args.smm_dir, "convention", resolved)
    return 0
