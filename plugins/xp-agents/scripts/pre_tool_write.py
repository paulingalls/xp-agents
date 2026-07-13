#!/usr/bin/env python3
"""PreToolUse hook for Write/Edit/MultiEdit: conflict detection, TDD, plan review.

All checks are file-based (coordination.json, marker files, tracker files).
No event log reads.
"""

import sys
from pathlib import Path
from typing import NamedTuple

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
    schedule_gate_active_data,
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
    """Heuristic: does the file path look like a test file?

    lang-ok: an enumeration of 13 ecosystems' test-naming conventions, in which
    Python is one peer among Go, Rust, Swift, Java/Kotlin/Scala, Ruby, C/C++,
    C#, PHP, Dart, Elixir and the JS/TS family. Coverage, not a leak — a new
    language is added by appending a branch. The per-branch predicates below all
    inherit this justification; do NOT copy one out of the function without
    stating why the new site is agnostic too.
    """
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


def _is_smm_write(smm_dir: Path | None, target_file: str | None, cwd: str) -> bool:
    """True if the write targets a file inside the SMM dir.

    SMM mutations are infrastructure, not implementation, so they are exempt
    from the schedule gate. Resolves relative target paths against cwd.
    """
    if not smm_dir or not target_file:
        return False
    p = Path(target_file)
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        p.resolve().relative_to(smm_dir.resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# Lead-only marker gates
# ---------------------------------------------------------------------------


class _LeadGate(NamedTuple):
    """A marker gate that applies to the LEAD only."""

    marker: markers.MarkerDef
    reason: str
    short: str
    plan_files_exempt: bool


# Checked in order; the first armed gate blocks. Teammates are exempt from ALL
# of them. Every marker lives in the SHARED SMM dir and a teammate can clear
# none of them: it never plans, it is dispatched BY /xp-assign, and — running
# headless — it has no user to answer an AskUserQuestion. So gating a teammate
# forbids the parallel pipeline's whole purpose (the lead plans/assigns story
# N+1 while a teammate executes story N) and strands the teammate mid-story
# with no recovery path. A gate added to this table inherits the exemption by
# construction; the hand-rolled gates this replaces defaulted the other way,
# which is how the plan gate came to forbid the pipeline unnoticed for months.
_LEAD_GATES: tuple[_LeadGate, ...] = (
    _LeadGate(
        markers.PLAN_AWAITING_REVIEW,
        "Run /xp-review-plan before writing code. "
        "Plan review extracts assumptions, decisions, and risks for the SMM.",
        "Plan review required before implementation.",
        plan_files_exempt=True,
    ),
    _LeadGate(
        markers.ASSIGN_PENDING,
        "Run /xp-assign to create the next story's branch and spawn its "
        "teammate (per-story pipeline — one spawn per invocation) "
        "before writing code.",
        "Work assignment required before implementation.",
        plan_files_exempt=True,
    ),
    _LeadGate(
        markers.QUESTION_GATE,
        "A blocking question needs the user's answer. AskUserQuestion is "
        "the ONLY way to clear this — it records the answer and lifts the "
        "gate. Do NOT record a decision/status event resolving the question "
        "id: it does not clear the gate and fabricates an answer the user "
        "never gave.",
        "Blocking question requires user answer.",
        plan_files_exempt=False,
    ),
)


def check_lead_gates(
    input_data: dict, smm_dir: Path | None, is_plan_file: bool
) -> None:
    """Raise BlockedError for the first armed lead-only gate. Teammates exempt.

    The marker stat runs BEFORE the teammate probe, and the probe runs at most
    once: run() is on the hot path for every Write/Edit/MultiEdit, and the
    common case — lead, nothing armed — must not pay for a cwd parse, an env
    read and a marker stat whose answer nothing consumes.

    *smm_dir* is handed to the probe rather than left to its env fallback: that
    leg reads $SMM_DIR and fails CLOSED without it, which would misread a live
    in-place teammate as the lead and over-gate it.
    """
    if smm_dir is None:
        return
    for gate in _LEAD_GATES:
        if gate.plan_files_exempt and is_plan_file:
            continue
        if not markers.marker_exists(smm_dir, gate.marker):
            continue
        if identity.is_worktree_teammate(input_data, smm_dir):
            return  # a teammate can clear none of these gates
        raise _common.BlockedError(gate.reason, gate.short)


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

    # Plan, assign and question gates — all lead-only, all exempt plan files
    # (.claude/plans/) except the question gate. See _LEAD_GATES.
    is_plan_file = bool(target_file and "/.claude/plans/" in target_file)
    check_lead_gates(input_data, smm_dir, is_plan_file)

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

        # Schedule gate (state-derived, no marker). In the pre-promotion window
        # (scheduled stories exist, no story in motion) force /xp-schedule before
        # implementation writes. SMM writes exempt (plan files already excluded
        # above). The in-motion guard keeps the gate quiet through the
        # /xp-accept review + /xp-story-close window so review-cycle fixes to the
        # closing story aren't blocked. Self-clears the instant a frontier is
        # promoted to in-progress.
        #
        # Deliberately NOT in _LEAD_GATES, and it needs no teammate exemption: it
        # is state-derived, not a marker. A teammate only exists once a frontier
        # is in motion — the very condition that makes this gate quiet — so a
        # teammate can never meet it. Do not copy this as the pattern for a
        # MARKER gate: a marker persists across the states that should clear it,
        # which is how the plan gate came to forbid the pipeline for months. A
        # new marker gate belongs in _LEAD_GATES.
        if (
            sprint_data is not None
            and schedule_gate_active_data(sprint_data)
            and not _is_smm_write(smm_dir, target_file, cwd)
        ):
            raise _common.BlockedError(
                "Run /xp-schedule to promote the next frontier (scheduled -> "
                "in-progress) and pick solo/teammate before writing code.",
                "Schedule the next frontier before implementation.",
            )

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
