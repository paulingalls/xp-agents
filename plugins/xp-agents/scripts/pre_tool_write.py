#!/usr/bin/env python3
"""PreToolUse hook for Write/Edit/MultiEdit: conflict detection, TDD, plan review.

All checks are file-based (coordination.json, marker files, tracker files).
No event log reads.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination

_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_TEST_DIRS = {"tests", "__tests__", "test"}


def is_test_file(path: str) -> bool:
    """Heuristic: does the file path look like a test file?"""
    p = Path(path)
    name = p.name
    parts = set(p.parts)

    # Directory-based
    if parts & _TEST_DIRS:
        return True

    # Name-based patterns
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    if name.endswith("_test.go"):
        return True
    if name.endswith("Test.java"):
        return True
    return bool(name.endswith("_spec.rb"))


# ---------------------------------------------------------------------------
# working_on overlap detection
# ---------------------------------------------------------------------------


def check_working_on_overlap(
    smm_dir: Path, agent_id: str, file_path: str, cwd: str
) -> str | None:
    """Check if another agent is working on the same file.

    Reads .coordination.json (O(1)) instead of scanning the event log.
    Returns conflict message or None.
    """
    coord_data = coordination.read_coordination(smm_dir)
    normalized_target = _common.normalize_path(file_path, cwd)

    for aid, entry in coord_data.items():
        if aid == agent_id:
            continue
        for f in entry.get("working_on", []):
            try:
                if _common.normalize_path(f, cwd) == normalized_target:
                    return (
                        f"CONFLICT: Agent '{aid}' is currently "
                        f"working on '{f}'. "
                        f"Coordinate before modifying this file."
                    )
            except (ValueError, OSError):
                continue

    return None


# ---------------------------------------------------------------------------
# TDD order tracking
# ---------------------------------------------------------------------------


def check_tdd_order(
    smm_dir: Path, agent_id: str, file_path: str, tool_name: str
) -> str | None:
    """Track writes and nudge if tests are missing. Returns nudge or None."""
    if tool_name not in _WRITE_TOOLS:
        return None
    if file_path is None:
        return None

    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None
    tracker_file = smm_dir / f".tdd-{agent_id}.json"

    # Load existing tracker
    try:
        tracker = json.loads(tracker_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        tracker = {"writes": [], "test_written": False}

    changed = False

    if is_test_file(file_path):
        if not tracker["test_written"]:
            tracker["test_written"] = True
            changed = True
        if changed:
            _write_tracker(tracker_file, tracker)
        return None

    # Implementation file
    if file_path not in tracker["writes"]:
        tracker["writes"].append(file_path)
        changed = True

    if changed:
        _write_tracker(tracker_file, tracker)

    # Grace period: first impl write doesn't trigger nudge
    if len(tracker["writes"]) < 2:
        return None

    if not tracker["test_written"]:
        return (
            "TDD reminder: You've written to "
            f"{len(tracker['writes'])} implementation files without a test. "
            "Consider writing a test first."
        )

    return None


def _write_tracker(tracker_file: Path, tracker: dict) -> None:
    """Atomic write of TDD tracker file."""
    _common.write_json_atomic(tracker_file, tracker)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core logic. Returns additionalContext string or None. Raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agent_id", "main")
    cwd = input_data.get("cwd", ".")

    enforcement = _common.load_enforcement_mode()

    parts: list[str] = []

    # Extract target_file (always present for Write/Edit/MultiEdit)
    target_file = _common.extract_file_path(tool_name, tool_input)

    # Conflict detection via .coordination.json (O(1), no event log scan)
    if target_file and smm_dir:
        conflict = check_working_on_overlap(smm_dir, agent_id, target_file, cwd)
        if conflict:
            concern_event = _common.make_event(
                _common.CONCERN,
                agent_id,
                conflict,
                severity="high",
            )
            _common.append_safe(smm_dir, concern_event)
            if enforcement == _common.ENFORCEMENT_ADVISORY:
                parts.append(f"Advisory warning: {conflict}")
            else:
                raise _common.BlockedError(
                    conflict,
                    "File conflict detected — another agent is working on this file.",
                )

    # Plan review gate — check marker file (O(1), no event log scan)
    if smm_dir:
        marker = smm_dir / ".plan-awaiting-review"
        if marker.exists() and not marker.is_symlink():
            parts.append(
                "Run /xp-plan-reviewer to review the plan before implementing."
            )

    # TDD order check
    if target_file and smm_dir:
        tdd_nudge = check_tdd_order(smm_dir, agent_id, target_file, tool_name)
        if tdd_nudge:
            parts.append(tdd_nudge)

    # Enforcement indicator
    if enforcement == _common.ENFORCEMENT_ADVISORY:
        parts.append("[enforcement: advisory]")

    if not parts:
        return None

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    try:
        result = run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    if result:
        _common.hook_output("PreToolUse", result)
