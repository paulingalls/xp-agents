#!/usr/bin/env python3
"""Load/save for system_context.json.

Python API for system context operations. Internal scripts import
these functions directly. Shell scripts and skills use system_context_cli.py
which wraps this module.

Follows the same pattern as execution_plan_store.py: atomic writes, schema
validation on save, fail-loud on corrupt reads, symlink rejection.
"""

import json
from pathlib import Path

import marker_names
from _append_impl import write_text_atomic
from system_context_schema import (
    SYSTEM_CONTEXT_FILENAME,
    validate_system_context,
)


def system_context_exists(smm_dir: Path) -> bool:
    """Check if system_context.json exists (not a symlink)."""
    path = smm_dir / SYSTEM_CONTEXT_FILENAME
    return path.exists() and not path.is_symlink()


def load_system_context(smm_dir: Path) -> dict | None:
    """Read the system context from disk.

    Returns:
        Parsed dict on success, or None if the file does not exist.

    Raises:
        ValueError: If the file exists but contains malformed JSON or
            fails schema validation.
        OSError: If the path is a symlink.
    """
    path = smm_dir / SYSTEM_CONTEXT_FILENAME
    if path.is_symlink():
        raise OSError(f"System context path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt system context at {path}: {exc}") from exc

    if isinstance(data, dict):
        if "key_decisions" in data and "principles" not in data:
            data["principles"] = data.pop("key_decisions")
        data.pop("sources", None)

    errors = validate_system_context(data, enforce_budget=False)
    if errors:
        raise ValueError(
            f"Schema-invalid system context at {path}: {'; '.join(errors)}"
        )
    return data


def acceptance_surface_names(smm_dir: Path) -> frozenset[str] | None:
    """Surface names from system_context, or None when none are declared.

    None signals "no FK to enforce" — a surface-name foreign key keyed on this
    set stays shape-only when a project declares no acceptance_surfaces; a
    frozenset turns it enforcing.

    Best-effort: a missing, corrupt, or schema-invalid system_context yields
    None rather than raising, since the FK is an enhancement, not a gate.
    Corruption and symlink attacks are surfaced on this module's own
    load/save paths; swallowing them here keeps a best-effort lookup from
    blocking an unrelated write.
    """
    try:
        doc = load_system_context(smm_dir)
    except (ValueError, OSError):
        return None
    surfaces = (doc or {}).get("acceptance_surfaces", [])
    names = frozenset(
        s["name"] for s in surfaces if isinstance(s, dict) and "name" in s
    )
    return names or None


def save_system_context(
    smm_dir: Path, data: dict, *, enforce_budget: bool = True
) -> None:
    """Validate and atomically write the system context.

    Clears the NEEDS_SYSTEM_CONTEXT marker on success.

    Raises:
        ValueError: If the data fails schema validation.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SYSTEM_CONTEXT_FILENAME
    if path.is_symlink():
        raise OSError(f"System context path is a symlink: {path}")

    errors = validate_system_context(data, enforce_budget=enforce_budget)
    if errors:
        raise ValueError(f"System context validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))
    (smm_dir / marker_names.NEEDS_SYSTEM_CONTEXT).unlink(missing_ok=True)
