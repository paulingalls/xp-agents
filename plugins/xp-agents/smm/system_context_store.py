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
    integration_branch_error,
    user_namespace_error,
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

    # enforce_ref_format=False: a stored integration_branch that predates the
    # git-ref rule must still LOAD, unchanged, or every session of a project
    # configured before the rule hard-fails. The value is healed where it is
    # USED as a ref (branch_resolution), never here — this loader feeds
    # `_maybe_auto_promote`'s load → mutate → save, which would persist the
    # substitute over the branch name the user configured.
    errors = validate_system_context(
        data, enforce_budget=False, enforce_ref_format=False
    )
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


_NO_STORED_VALUE = object()


def _stored_branching_field(path: Path, field: str) -> object:
    """The branching_strategy *field* currently on disk, or ``_NO_STORED_VALUE``.

    FAILS CLOSED. A missing, corrupt, symlinked or unreadable document is no
    proof that a value was already stored, so it yields the sentinel — which
    compares equal to nothing and therefore grandfathers nothing. A
    grandfather that failed open would not be a grandfather; it would be an
    unconditional bypass reachable by deleting a file.
    """
    if path.is_symlink():
        return _NO_STORED_VALUE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _NO_STORED_VALUE
    if not isinstance(doc, dict):
        return _NO_STORED_VALUE
    bs = doc.get("branching_strategy")
    if not isinstance(bs, dict) or field not in bs:
        return _NO_STORED_VALUE
    return bs[field]


# Every branching_strategy field the git-ref rule governs, with the validator
# that reports it. Keyed by field so the grandfather stays per-FIELD while
# ``enforce_ref_format`` remains document-wide.
_REF_FORMAT_VALIDATORS = {
    "integration_branch": integration_branch_error,
    "user_namespace": user_namespace_error,
}


def _is_grandfathered_ref_format(path: Path, data: dict) -> bool:
    """True when EVERY ref-format violation in *data* is a value already stored.

    Compares FIELDS, never whole-document equality: the round-trip this exists
    for (`branch_resolution._maybe_auto_promote`) loads the doc, changes the
    stage, and saves — the document differs, the fields do not. NEW bad input is
    still rejected; only re-writing a value the project already had is allowed
    through.

    ALL violations must match, because ``enforce_ref_format`` is document-wide:
    a grandfathered integration_branch must not license a brand-new unusable
    user_namespace riding along in the same save.

    False when nothing violates the rule: there is nothing to grandfather, the
    strict flag stays UP, and the common save skips the extra disk read.
    """
    bs = data.get("branching_strategy")
    if not isinstance(bs, dict):
        return False
    offenders = [f for f, err in _REF_FORMAT_VALIDATORS.items() if err(bs) is not None]
    if not offenders:
        return False
    return all(f in bs and bs[f] == _stored_branching_field(path, f) for f in offenders)


def save_system_context(
    smm_dir: Path, data: dict, *, enforce_budget: bool = True
) -> None:
    """Validate and atomically write the system context.

    Clears the NEEDS_SYSTEM_CONTEXT marker on success.

    The git-ref rule on integration_branch and user_namespace is enforced
    STRICTLY here — the write path is where a bad value gets in — but
    grandfathered: a value already on disk may be written back, so an internal
    load/save round-trip of a config that predates the rule does not crash. See
    ``_is_grandfathered_ref_format``.

    Raises:
        ValueError: If the data fails schema validation.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SYSTEM_CONTEXT_FILENAME
    if path.is_symlink():
        raise OSError(f"System context path is a symlink: {path}")

    errors = validate_system_context(
        data,
        enforce_budget=enforce_budget,
        enforce_ref_format=not _is_grandfathered_ref_format(path, data),
    )
    if errors:
        raise ValueError(f"System context validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))
    (smm_dir / marker_names.NEEDS_SYSTEM_CONTEXT).unlink(missing_ok=True)
