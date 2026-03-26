#!/usr/bin/env python3
"""Marker file infrastructure for the XP-agents plugin.

Consolidates all marker file operations (path, read, write, exists, consume)
into a single module with uniform symlink safety and atomic writes.

Marker definitions are frozen dataclass descriptors. Generic operations
accept a MarkerDef to determine file name and content strategy.
"""

import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import _validate_agent_id, write_json_atomic, write_text_atomic

# ---------------------------------------------------------------------------
# MarkerDef descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarkerDef:
    """Descriptor for a marker file in the SMM directory."""

    name: str
    content_type: Literal["text", "json"]
    agent_scoped: bool = False

    def filename(self, agent_id: str = "") -> str:
        """Return the concrete filename, substituting agent_id if scoped."""
        if self.agent_scoped:
            if not agent_id:
                raise ValueError("agent_id required for agent-scoped marker")
            _validate_agent_id(agent_id)
            return self.name.format(agent_id=agent_id)
        return self.name


# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

KICKOFF = MarkerDef(".needs-kickoff", "text")
SECURITY_TRIAGED = MarkerDef(".security-triaged", "json")
PLAN_AWAITING_REVIEW = MarkerDef(".plan-awaiting-review", "text")
TDD_TRACKER = MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
REVIEW_CYCLE = MarkerDef(".review-cycle-{agent_id}.json", "json", agent_scoped=True)


# ---------------------------------------------------------------------------
# Generic operations
# ---------------------------------------------------------------------------


def marker_path(smm_dir: Path, marker: MarkerDef, agent_id: str = "") -> Path:
    """Return the full path to a marker file."""
    return smm_dir / marker.filename(agent_id)


def marker_exists(smm_dir: Path, marker: MarkerDef, agent_id: str = "") -> bool:
    """Check if a marker file exists (symlink-safe, validates JSON content)."""
    path = marker_path(smm_dir, marker, agent_id)
    if not path.exists() or path.is_symlink():
        return False
    if marker.content_type == "json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(data, dict)
        except (OSError, json.JSONDecodeError, ValueError):
            return False
    return True


def marker_read(
    smm_dir: Path, marker: MarkerDef, agent_id: str = ""
) -> str | dict | None:
    """Read a marker file's content. Returns None if missing, symlink, or corrupt."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    match marker.content_type:
        case "json":
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        case "text":
            return raw.strip()


def marker_write(
    smm_dir: Path, marker: MarkerDef, data: str | dict, agent_id: str = ""
) -> None:
    """Atomically write a marker file. Rejects symlinks."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {path}")
    match marker.content_type:
        case "json":
            write_json_atomic(path, data)
        case "text":
            write_text_atomic(path, data if isinstance(data, str) else str(data))


def marker_consume(
    smm_dir: Path, marker: MarkerDef, agent_id: str = ""
) -> str | dict | None:
    """Read a marker file and delete it. Returns None if missing or symlink."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        return None
    result = marker_read(smm_dir, marker, agent_id)
    with contextlib.suppress(OSError):
        path.unlink()
    return result
