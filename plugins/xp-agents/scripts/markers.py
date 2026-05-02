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

import marker_names
from _append_impl import write_json_atomic, write_text_atomic
from append_validation import validate_agent_id

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
            validate_agent_id(agent_id)
            return self.name.format(agent_id=agent_id)
        return self.name


# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

KICKOFF = MarkerDef(marker_names.KICKOFF, "text")
NEEDS_EXECUTION_PLAN = MarkerDef(marker_names.NEEDS_EXECUTION_PLAN, "text")
NEEDS_SYSTEM_CONTEXT = MarkerDef(marker_names.NEEDS_SYSTEM_CONTEXT, "text")
NEEDS_SPRINT = MarkerDef(marker_names.NEEDS_SPRINT, "text")
ACCEPT = MarkerDef(marker_names.ACCEPT, "text")
PLAN_AWAITING_REVIEW = MarkerDef(marker_names.PLAN_AWAITING_REVIEW, "text")
QUESTION_GATE = MarkerDef(marker_names.QUESTION_GATE, "text")
ASKING_USER = MarkerDef(marker_names.ASKING_USER, "text")
ASSIGN_PENDING = MarkerDef(marker_names.ASSIGN_PENDING, "text")
NEEDS_HOUSEKEEPING = MarkerDef(marker_names.NEEDS_HOUSEKEEPING, "text")
TDD_TRACKER = MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
REVIEW_CYCLE = MarkerDef(".review-cycle-{agent_id}.json", "json", agent_scoped=True)
QUESTION_NUDGED = MarkerDef(marker_names.QUESTION_NUDGED, "json", agent_scoped=True)


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
            if not isinstance(data, dict):
                raise TypeError(f"JSON marker requires dict, got {type(data)}")
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


# ---------------------------------------------------------------------------
# Review cycle convenience functions (API surface for M2)
# ---------------------------------------------------------------------------

_DEFAULT_REVIEW_CYCLE: dict = {
    "last_review_commit": "",
    "simplify_done": False,
    "quality_review_done": False,
}

_REVIEW_FLAGS = frozenset({"simplify_done", "quality_review_done"})


def read_review_cycle(smm_dir: Path, agent_id: str) -> dict:
    """Read review cycle marker, returning defaults if missing."""
    data = marker_read(smm_dir, REVIEW_CYCLE, agent_id)
    if not isinstance(data, dict):
        return dict(_DEFAULT_REVIEW_CYCLE)
    return data


def write_review_cycle(smm_dir: Path, agent_id: str, data: dict) -> None:
    """Write review cycle marker."""
    marker_write(smm_dir, REVIEW_CYCLE, data, agent_id)


def reset_review_cycle(smm_dir: Path, agent_id: str, commit_hash: str) -> None:
    """Reset review cycle: new commit hash, all flags cleared."""
    data = dict(_DEFAULT_REVIEW_CYCLE)
    data["last_review_commit"] = commit_hash
    write_review_cycle(smm_dir, agent_id, data)


def set_review_flag(
    smm_dir: Path, agent_id: str, flag: str, value: bool = True
) -> None:
    """Set a single review flag (read-modify-write)."""
    if flag not in _REVIEW_FLAGS:
        raise ValueError(f"Invalid review cycle flag: {flag!r}")
    data = read_review_cycle(smm_dir, agent_id)
    data[flag] = value
    write_review_cycle(smm_dir, agent_id, data)


# ---------------------------------------------------------------------------
# Agent cleanup
# ---------------------------------------------------------------------------

_AGENT_SCOPED_MARKERS: tuple[MarkerDef, ...] = (
    TDD_TRACKER,
    REVIEW_CYCLE,
    QUESTION_NUDGED,
)


def cleanup_agent_markers(smm_dir: Path, agent_id: str) -> None:
    """Remove all agent-scoped marker files for the given agent."""
    for marker in _AGENT_SCOPED_MARKERS:
        path = marker_path(smm_dir, marker, agent_id)
        with contextlib.suppress(OSError):
            path.unlink()
