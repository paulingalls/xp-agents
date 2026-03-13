#!/usr/bin/env python3
"""PreToolUse command hook: delta injection, conflict prevention, TDD tracking.

Fires on every tool call. Classifies the tool into a tier for delta injection,
checks for working_on overlap (conflict prevention), and nudges TDD ordering.
"""

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import read_delta

# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

_FULL_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
_RED_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob"})


def classify_tier(tool_name: str, tool_input: dict) -> str:
    """Classify tool into delta injection tier."""
    if tool_name in _FULL_TOOLS:
        return read_delta.TIER_FULL
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if "git commit" in command:
            return read_delta.TIER_FULL
        return read_delta.TIER_BLOCKING
    return read_delta.TIER_RED_ONLY


# ---------------------------------------------------------------------------
# Target file extraction
# ---------------------------------------------------------------------------


def get_target_file(tool_name: str, tool_input: dict) -> str | None:
    """Extract the target file path from tool_input, if applicable."""
    if tool_name in _FULL_TOOLS:
        return tool_input.get("file_path")
    return None


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
# Path normalization
# ---------------------------------------------------------------------------


def _normalize_path(file_path: str, cwd: str) -> str:
    """Resolve a file path against cwd, return normalized string."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    # Use os.path.normpath for .. resolution without touching filesystem
    return os.path.normpath(str(p))


# ---------------------------------------------------------------------------
# working_on overlap detection
# ---------------------------------------------------------------------------


def check_working_on_overlap(
    events: list[dict], agent_id: str, file_path: str, cwd: str
) -> str | None:
    """Check if another agent is working on the same file. Returns message or None."""
    normalized_target = _normalize_path(file_path, cwd)

    # Build map: agent_id -> latest status event's working_on files
    agent_files: dict[str, list[str]] = {}
    for event in events:
        if event.get("type") == "status" and event.get("working_on"):
            aid = event.get("agent_id", "")
            agent_files[aid] = event["working_on"]

    for aid, files in agent_files.items():
        if aid == agent_id:
            continue
        normalized_files = {_normalize_path(f, cwd) for f in files}
        if normalized_target in normalized_files:
            # Find the original path for the message
            conflicting = next(
                f for f in files if _normalize_path(f, cwd) == normalized_target
            )
            return (
                f"CONFLICT: Agent '{aid}' is currently working on '{conflicting}'. "
                f"Coordinate before modifying this file."
            )

    return None


# ---------------------------------------------------------------------------
# TDD order tracking
# ---------------------------------------------------------------------------


def check_tdd_order(
    smm_dir: Path, agent_id: str, file_path: str, tool_name: str
) -> str | None:
    """Track writes and nudge if tests are missing. Returns nudge or None."""
    if tool_name not in _FULL_TOOLS:
        return None
    if file_path is None:
        return None

    _common._validate_agent_id(agent_id)
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
    fd, tmp = tempfile.mkstemp(
        dir=tracker_file.parent,
        prefix=".tdd-tmp-",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(tracker, f)
        os.chmod(tmp, 0o600)
        os.rename(tmp, tracker_file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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

    # Classify tier and get target file
    tier = classify_tier(tool_name, tool_input)
    target_file = get_target_file(tool_name, tool_input)

    # Check working_on overlap (only for write tools with a target file)
    # Uses lockless read — overlap detection is best-effort
    if target_file and smm_dir:
        events = _common.read_events_raw(smm_dir)
        conflict = check_working_on_overlap(events, agent_id, target_file, cwd)
        if conflict:
            raise _common.BlockedError(conflict)

    # Read delta (separate locked read with watermark tracking)
    parts: list[str] = []
    if smm_dir:
        delta_events = read_delta.read_delta(smm_dir, agent_id, tier=tier)
        delta_text = read_delta.format_delta(delta_events)
        if delta_text:
            parts.append(delta_text)

    # TDD order check
    if target_file and smm_dir:
        tdd_nudge = check_tdd_order(smm_dir, agent_id, target_file, tool_name)
        if tdd_nudge:
            parts.append(tdd_nudge)

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
