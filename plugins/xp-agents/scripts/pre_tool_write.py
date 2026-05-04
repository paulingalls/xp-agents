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

_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_TEST_DIRS = {"tests", "__tests__", "test", "spec"}
_TEST_DIR_SUFFIXES = ("Tests",)  # Xcode: ContactForgeTests/
# Maven/Gradle: src/test/java/...
_TEST_PATH_SEGMENTS = {"src/test"}
# JS/TS lacks a canonical test extension — enumerate the family
# (.ts/.tsx/.js/.jsx + ESM/CJS module variants).
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

    # Directory-based: exact match
    if parts & _TEST_DIRS:
        return True

    # Directory suffix: *Tests/ (Xcode convention)
    if any(part.endswith("Tests") for part in p.parts):
        return True

    # Path segment: src/test (Maven/Gradle)
    if any(seg in path_str for seg in _TEST_PATH_SEGMENTS):
        return True

    # Name contains .test. or .spec. (JS/TS: app.test.js, app.spec.ts)
    if ".test." in name or ".spec." in name:
        return True

    # JS/TS underscore convention (Bun/some monorepos use foo_test.ts
    # alongside the more common foo.test.ts).
    if name.endswith(_JS_TS_TEST_SUFFIXES):
        return True

    # Python: test_*.py, *_test.py
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True

    # Go: *_test.go
    if name.endswith("_test.go"):
        return True

    # Swift: *Tests.swift
    if name.endswith("Tests.swift"):
        return True

    # Java/Kotlin: *Test.java, *Tests.java, *Test.kt, *Tests.kt
    if (stem.endswith("Test") or stem.endswith("Tests")) and p.suffix in {
        ".java",
        ".kt",
        ".scala",
    }:
        return True

    # Ruby: *_spec.rb, *_test.rb
    if name.endswith("_spec.rb") or name.endswith("_test.rb"):
        return True

    # Rust: *_test.rs, tests/*.rs (tests/ already caught above)
    if name.endswith("_test.rs"):
        return True

    # C/C++: test_*.c, test_*.cpp, *_test.c, *_test.cpp
    if p.suffix in {".c", ".cpp", ".cc", ".cxx"} and (
        stem.startswith("test_") or stem.endswith("_test")
    ):
        return True

    # C#: *Test.cs, *Tests.cs
    if p.suffix == ".cs" and (stem.endswith("Test") or stem.endswith("Tests")):
        return True

    # PHP: *Test.php
    if name.endswith("Test.php"):
        return True

    # Dart/Flutter: *_test.dart
    if name.endswith("_test.dart"):
        return True

    # Elixir: *_test.exs
    return bool(name.endswith("_test.exs"))


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
    normalized_target = worktree.normalize_path(file_path, cwd)

    for aid, entry in coord_data.items():
        if aid == agent_id:
            continue
        for f in entry.get("working_on", []):
            try:
                if worktree.normalize_path(f, cwd) == normalized_target:
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
        append_validation.validate_agent_id(agent_id)
    except ValueError:
        return None

    # Load existing tracker
    raw = markers.marker_read(smm_dir, markers.TDD_TRACKER, agent_id)
    tracker: dict = (
        raw
        if isinstance(raw, dict)
        else {
            "writes": [],
            "test_written": False,
        }
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

    # Implementation file
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
            "TDD reminder: You've written to "
            f"{len(tracker['writes'])} implementation files without a test. "
            "Consider writing a test first."
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
                files=[target_file],
            )
            _common.append_safe(smm_dir, concern_event)
            raise _common.BlockedError(
                conflict,
                "File conflict detected — another agent is working on this file.",
            )

    # Plan review gate — block writes until plan is reviewed.
    # Plan files (.claude/plans/) are exempt — writing the plan is not implementation.
    is_plan_file = target_file and "/.claude/plans/" in target_file
    plan_marker = (
        smm_dir
        and not is_plan_file
        and markers.marker_exists(smm_dir, markers.PLAN_AWAITING_REVIEW)
    )
    if plan_marker:
        raise _common.BlockedError(
            "Run /xp-review-plan before writing any code. "
            "The plan review extracts assumptions, decisions, and risks "
            "that feed the Shared Mental Model.",
            "Plan review required before implementation.",
        )

    # Assign gate — block writes until /xp-assign decides execution mode.
    # Plan files (.claude/plans/) are exempt — same as plan review gate.
    assign_marker = (
        smm_dir
        and not is_plan_file
        and markers.marker_exists(smm_dir, markers.ASSIGN_PENDING)
    )
    if assign_marker:
        raise _common.BlockedError(
            "Run /xp-assign to decide execution mode "
            "(solo vs worktree subagents) before writing code.",
            "Work assignment required before implementation.",
        )

    # Question gate — block writes until blocking question is answered.
    question_gate = smm_dir and markers.marker_exists(smm_dir, markers.QUESTION_GATE)
    if question_gate:
        raise _common.BlockedError(
            "A blocking question needs your answer. "
            "Use AskUserQuestion to ask the user, then proceed.",
            "Blocking question requires user answer.",
        )

    # TDD order check
    if target_file and smm_dir:
        tdd_nudge = check_tdd_order(smm_dir, agent_id, target_file, tool_name)
        if tdd_nudge:
            parts.append(tdd_nudge)

    # Accept marker — signal "needs acceptance" when writing during active sprint.
    # Plan files are exempt (writing a plan isn't iteration work). ACCEPT_ACTIVE
    # suppresses re-arm during xp-accept fix-cycles in multi-in-progress sprints
    # (where reviewing carve-out alone isn't enough — other stories keep
    # has_in_progress_stories True).
    if (
        smm_dir
        and not is_plan_file
        and sprint_state.has_in_progress_stories(smm_dir)
        and not markers.marker_exists(smm_dir, markers.ACCEPT)
        and not markers.marker_exists(smm_dir, markers.ACCEPT_ACTIVE)
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
