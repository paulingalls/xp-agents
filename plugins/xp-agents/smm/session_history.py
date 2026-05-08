#!/usr/bin/env python3
"""Persistent ring-buffer for session_history.json.

session_history.json sits beside events.jsonl in SMM_DIR and holds the
last N session summaries plus their carry_forward items. Schema is
versioned so future migrations can introspect the on-disk shape:

    {
      "version": 1,
      "entries": [
        {
          "ts": ISO-8601 string,
          "summary": str,
          "carry_forward": [
            {"note": str, "references": [event_id, ...], "recommendation": str},
            ...
          ]
        },
        ...
      ]
    }

I/O follows the smm_store / system_context_store template: atomic write
via tempfile + rename, symlink rejection, fail-loud on corrupt JSON or
schema-invalid content. Pure module — no CLI; story-003's write_history.py
is the CLI front-end.
"""

import json
from pathlib import Path

from _append_impl import write_text_atomic
from resolution import collect_all_resolved_ids

SESSION_HISTORY_FILENAME = "session_history.json"
SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 5


def validate_session_history(data: object) -> list[str]:
    """Validate a session history document.

    Returns a list of error strings — empty list means valid. Mirrors
    ``smm_schema.validate_smm`` contract.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["session_history must be an object"]

    if data.get("version") != SCHEMA_VERSION:
        errors.append(
            f"session_history version must be {SCHEMA_VERSION}, "
            f"got {data.get('version')!r}"
        )

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("session_history.entries must be an array")
        return errors

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{idx}] must be an object")
            continue
        if not isinstance(entry.get("ts"), str):
            errors.append(f"entries[{idx}].ts must be a string")
        if not isinstance(entry.get("summary"), str):
            errors.append(f"entries[{idx}].summary must be a string")
        cf = entry.get("carry_forward")
        if not isinstance(cf, list):
            errors.append(f"entries[{idx}].carry_forward must be an array")
            continue
        for cf_idx, item in enumerate(cf):
            if not isinstance(item, dict):
                errors.append(
                    f"entries[{idx}].carry_forward[{cf_idx}] must be an object"
                )
                continue
            # `references` is the one field prune_resolved relies on; pin
            # its shape so corrupt data fails loud at save/load time
            # rather than silently surviving the prune cascade.
            refs = item.get("references")
            if refs is not None and not (
                isinstance(refs, list) and all(isinstance(r, str) for r in refs)
            ):
                errors.append(
                    f"entries[{idx}].carry_forward[{cf_idx}].references "
                    "must be a list of strings"
                )

    return errors


def empty_history() -> dict:
    """Return a fresh, valid session_history document."""
    return {"version": SCHEMA_VERSION, "entries": []}


def load_history(smm_dir: Path) -> dict:
    """Read session_history.json from disk.

    Returns:
        Parsed dict on success, or ``empty_history()`` if the file does
        not exist (fresh install / first session).

    Raises:
        ValueError: If the file exists but contains malformed JSON or
            fails schema validation.
        OSError: If the path is a symlink.
    """
    path = smm_dir / SESSION_HISTORY_FILENAME
    if path.is_symlink():
        raise OSError(f"session_history path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_history()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt session_history at {path}: {exc}") from exc

    errors = validate_session_history(data)
    if errors:
        raise ValueError(
            f"Schema-invalid session_history at {path}: {'; '.join(errors)}"
        )
    return data


def save_history(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write session_history.json.

    Raises:
        ValueError: If the data fails schema validation. The existing
            file on disk is left untouched.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SESSION_HISTORY_FILENAME
    if path.is_symlink():
        raise OSError(f"session_history path is a symlink: {path}")

    errors = validate_session_history(data)
    if errors:
        raise ValueError(f"session_history validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))


def append_entry(
    smm_dir: Path, entry: dict, *, max_entries: int = DEFAULT_MAX_ENTRIES
) -> None:
    """Append a single entry, evicting oldest entries beyond ``max_entries``.

    Newest entry is appended at the end; eviction trims the head so the
    surviving slice is the most-recent ``max_entries`` in chronological
    order. Caller is responsible for entry validity — save_history will
    reject malformed shapes loudly.
    """
    data = load_history(smm_dir)
    data["entries"].append(entry)
    if len(data["entries"]) > max_entries:
        data["entries"] = data["entries"][-max_entries:]
    save_history(smm_dir, data)


def prune_resolved(smm_dir: Path, resolutions: dict) -> int:
    """Drop carry_forward items whose every reference is now resolved.

    Walks each entry's carry_forward; an item is dropped iff it has at
    least one reference AND every reference id appears in
    ``resolution.collect_all_resolved_ids(resolutions)``. Items with no
    references are kept (no resolution claim possible). Saves only when
    at least one item was dropped.

    Returns the number of carry_forward items pruned.
    """
    resolved_ids = collect_all_resolved_ids(resolutions)
    if not resolved_ids:
        return 0

    data = load_history(smm_dir)
    pruned_count = 0
    for entry in data["entries"]:
        original = entry.get("carry_forward", [])
        kept: list[dict] = []
        for item in original:
            refs = item.get("references", [])
            if refs and all(ref in resolved_ids for ref in refs):
                pruned_count += 1
                continue
            kept.append(item)
        entry["carry_forward"] = kept

    if pruned_count:
        save_history(smm_dir, data)
    return pruned_count
