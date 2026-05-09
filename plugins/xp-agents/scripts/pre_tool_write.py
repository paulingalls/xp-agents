#!/usr/bin/env python3
"""PreToolUse hook for Write/Edit/MultiEdit: conflict detection, TDD, plan review.

All checks are file-based (coordination.json, marker files, tracker files).
No event log reads.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import append_validation
import code_files
import coordination
import identity
import markers
import sprint_state
import worktree
from sprint_status import (
    has_in_progress_stories_data,
    has_under_acceptance_stories_data,
)

# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_TEST_DIRS = {"tests", "__tests__", "test", "spec"}
_TEST_PATH_SEGMENTS = {"src/test"}  # Maven/Gradle
# JS/TS lacks a canonical test extension — enumerate the family.
_JS_TS_TEST_SUFFIXES = (
    "_test.ts",
    "_test.tsx",
    "_test.js",
    "_test.jsx",
    "_test.mts",
    "_test.cts",
    "_test.mjs",
    "_test.cjs",
)


def is_test_file(path: str) -> bool:
    """Heuristic: does the file path look like a test file?"""
    p = Path(path)
    name = p.name
    stem = p.stem
    parts = set(p.parts)
    path_str = str(p)

    if parts & _TEST_DIRS:
        return True

    # *Tests/ directory (Xcode)
    if any(part.endswith("Tests") for part in p.parts):
        return True

    if any(seg in path_str for seg in _TEST_PATH_SEGMENTS):
        return True

    # JS/TS: app.test.js, app.spec.ts
    if ".test." in name or ".spec." in name:
        return True

    if name.endswith(_JS_TS_TEST_SUFFIXES):
        return True

    # Python
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True

    # Go
    if name.endswith("_test.go"):
        return True

    # Swift
    if name.endswith("Tests.swift"):
        return True

    # Java/Kotlin/Scala
    if (stem.endswith("Test") or stem.endswith("Tests")) and p.suffix in {
        ".java",
        ".kt",
        ".scala",
    }:
        return True

    # Ruby
    if name.endswith("_spec.rb") or name.endswith("_test.rb"):
        return True

    # Rust
    if name.endswith("_test.rs"):
        return True

    # C/C++
    if p.suffix in {".c", ".cpp", ".cc", ".cxx"} and (
        stem.startswith("test_") or stem.endswith("_test")
    ):
        return True

    # C#
    if p.suffix == ".cs" and (stem.endswith("Test") or stem.endswith("Tests")):
        return True

    # PHP
    if name.endswith("Test.php"):
        return True

    # Dart
    if name.endswith("_test.dart"):
        return True

    # Elixir
    return bool(name.endswith("_test.exs"))


# ---------------------------------------------------------------------------
# working_on overlap detection
# ---------------------------------------------------------------------------


def check_working_on_overlap(
    smm_dir: Path, agent_id: str, file_path: str, cwd: str
) -> str | None:
    """Check if another agent is working on the same file.

    Reads .coordination.json (O(1)) instead of scanning the event log.
    """
    coord_data = coordination.read_coordination(smm_dir)
    normalized_target = worktree.normalize_path(file_path, cwd)

    for aid, entry in coord_data.items():
        if aid == agent_id:
            continue
        for f in entry.get("working_on", []):
            try:
                if worktree.normalize_path(f, cwd) == normalized_target:
                    return (
                        f"CONFLICT: Agent '{aid}' is working on '{f}'. "
                        f"Coordinate before modifying."
                    )
            except (ValueError, OSError):
                continue

    return None


# ---------------------------------------------------------------------------
# TDD order tracking
# ---------------------------------------------------------------------------


def check_tdd_order(smm_dir: Path, agent_id: str, file_path: str | None) -> str | None:
    """Track writes and nudge if tests are missing. Returns nudge or None."""
    if file_path is None:
        return None

    try:
        append_validation.validate_agent_id(agent_id)
    except ValueError:
        return None

    raw = markers.marker_read(smm_dir, markers.TDD_TRACKER, agent_id)
    tracker: dict = (
        raw if isinstance(raw, dict) else {"writes": [], "test_written": False}
    )

    changed = False

    if is_test_file(file_path):
        if not tracker["test_written"]:
            tracker["test_written"] = True
            changed = True
        if changed:
            markers.marker_write(smm_dir, markers.TDD_TRACKER, tracker, agent_id)
        return None

    # Non-code files (md, json, yaml, etc.) don't count for TDD tracking
    if not code_files.is_code_file(file_path):
        return None

    if file_path not in tracker["writes"]:
        tracker["writes"].append(file_path)
        changed = True

    if changed:
        markers.marker_write(smm_dir, markers.TDD_TRACKER, tracker, agent_id)

    # Grace period: first impl write doesn't trigger nudge
    if len(tracker["writes"]) < 2:
        return None

    if not tracker["test_written"]:
        return (
            f"TDD reminder: {len(tracker['writes'])} implementation files "
            f"written without a test. Write a test first."
        )

    return None


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core logic. Returns additionalContext string or None. Raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = identity.resolve_agent_id(input_data)
    cwd = input_data.get("cwd", ".")

    parts: list[str] = []

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
                files=[target_file],
            )
            _common.append_safe(smm_dir, concern_event)
            raise _common.BlockedError(
                conflict,
                "File conflict detected — another agent is working on this file.",
            )

    # Plan review gate. Plan files (.claude/plans/) are exempt.
    is_plan_file = target_file and "/.claude/plans/" in target_file
    plan_marker = (
        smm_dir
        and not is_plan_file
        and markers.marker_exists(smm_dir, markers.PLAN_AWAITING_REVIEW)
    )
    if plan_marker:
        raise _common.BlockedError(
            "Run /xp-review-plan before writing code. "
            "Plan review extracts assumptions, decisions, and risks for the SMM.",
            "Plan review required before implementation.",
        )

    # Assign gate. Plan files exempt — same as plan review gate.
    assign_marker = (
        smm_dir
        and not is_plan_file
        and markers.marker_exists(smm_dir, markers.ASSIGN_PENDING)
    )
    if assign_marker:
        raise _common.BlockedError(
            "Run /xp-assign to decide execution mode (solo vs worktree subagents) "
            "before writing code.",
            "Work assignment required before implementation.",
        )

    # Question gate
    question_gate = smm_dir and markers.marker_exists(smm_dir, markers.QUESTION_GATE)
    if question_gate:
        raise _common.BlockedError(
            "A blocking question needs your answer. Use AskUserQuestion.",
            "Blocking question requires user answer.",
        )

    if target_file and smm_dir:
        tdd_nudge = check_tdd_order(smm_dir, agent_id, target_file)
        if tdd_nudge:
            parts.append(tdd_nudge)

    # Accept marker — signal "needs acceptance" when writing during an active
    # sprint. Plan files exempt. UNDER_ACCEPTANCE (reviewing/closing) suppresses
    # re-arm during the close-then-done window so fix-cycle Edits don't re-arm
    # .accept while the per-story accept dispatch is in flight.
    if smm_dir and not is_plan_file:
        sprint_data = sprint_state.read_sprint_content(smm_dir)
        if (
            sprint_data is not None
            and has_in_progress_stories_data(sprint_data)
            and not has_under_acceptance_stories_data(sprint_data)
            and not markers.marker_exists(smm_dir, markers.ACCEPT)
        ):
            markers.marker_write(smm_dir, markers.ACCEPT, "done")

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
