#!/usr/bin/env python3
"""Load/save for shared_mental_model.json.

The curated SMM is the persistent store for pillar content. This module
owns all I/O for that file: atomic writes, schema validation on save,
fail-loud on corrupt reads, symlink rejection.

Counterpart to smm_schema.py (pure validation) and smm_cli.py (rendering
and CLI). This module is stateful — it touches the filesystem.
"""

import json
from pathlib import Path

from _append_impl import write_text_atomic
from smm_schema import empty_smm, validate_smm

SMM_FILENAME = "shared_mental_model.json"


def load_smm(smm_dir: Path) -> dict:
    """Read the curated SMM from disk.

    Returns:
        Parsed SMM dict on success, or ``empty_smm()`` if the file
        does not exist (fresh install).

    Raises:
        ValueError: If the file exists but contains malformed JSON or
            fails schema validation. This is deliberate — silently
            returning empty on corruption would re-create the seed-wipe
            bug this module was built to fix.
        OSError: If the path is a symlink.
    """
    path = smm_dir / SMM_FILENAME
    if path.is_symlink():
        raise OSError(f"SMM path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_smm()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt SMM file at {path}: {exc}") from exc

    errors = validate_smm(data)
    if errors:
        raise ValueError(f"Schema-invalid SMM file at {path}: {'; '.join(errors)}")

    return data


def save_smm(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write the curated SMM.

    Raises:
        ValueError: If the data fails schema validation. The existing
            file on disk is left untouched.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SMM_FILENAME
    if path.is_symlink():
        raise OSError(f"SMM path is a symlink: {path}")

    errors = validate_smm(data)
    if errors:
        raise ValueError(f"SMM validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))
