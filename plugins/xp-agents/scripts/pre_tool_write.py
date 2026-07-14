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
import branch_names
import code_files
import coordination
import identity
import markers
import sprint_state
import worktree
from lead_gates import check_lead_gates
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


def _resolves_under(target_file: str, base: Path | str, cwd: str) -> bool:
    """True if `target_file` resolves to a path inside `base`.

    BOTH sides are resolved, and that is the whole point. git reports the
    PHYSICAL toplevel and $SMM_DIR may itself be a symlink, while a target built
    from the hook payload's cwd runs through whatever symlinks the caller had (on
    macOS /tmp is /private/tmp, and mkdtemp hands back /var/folders ->
    /private/var/folders). Resolve one side only and every contained path reads
    as outside — for the schedule gate that means failing OPEN for exactly the
    case it exists to catch.

    Shared by both exemption predicates below. Sharing the path MATH is not
    unioning the exemptions: they stay two predicates with two justifications
    (see the gate in run()) and only agree on what "inside a directory" means.
    """
    p = Path(target_file)
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        p.resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_smm_write(smm_dir: Path | None, target_file: str | None, cwd: str) -> bool:
    """True if the write targets a file inside the SMM dir.

    SMM mutations are infrastructure, not implementation, so they are exempt
    from the schedule gate — and, because sprint.json lives there, an SMM write
    is also the repair path when the sprint is unreadable.
    """
    if not smm_dir or not target_file:
        return False
    return _resolves_under(target_file, smm_dir, cwd)


def _is_outside_tree(target_file: str | None, root: str, cwd: str) -> bool:
    """True if the write targets a path outside the git working tree.

    No target is not evidence of being outside, so the gate stands.
    """
    if not target_file:
        return False
    return not _resolves_under(target_file, root, cwd)


def _is_out_of_story_scope(target_file: str | None, cwd: str) -> bool:
    """True if the write is outside what the schedule gate governs.

    The gate's claim is "do not write story code before the story is promoted",
    and two kinds of write are not story code: one that lands OUTSIDE the working
    tree (a memory file under ~/.claude is not this sprint's implementation — and
    the only way to satisfy the gate for it was to promote a story against a
    customer pause), and one made on a FREE branch, where the sprint is not the
    frame at all and /xp-free-close is the right path.

    Free-branch detection keys on branch SHAPE, never on a marker: a marker can be
    `rm`'d to bypass the gate, a branch name cannot be forged without being on it.

    Fails closed at every leg. No git root (not a repo, git broken) -> we cannot
    prove the write is out of scope, so we do not exempt it. `get_current_branch`
    returns "" on git failure and the literal "HEAD" when detached; neither is a
    free branch, so both leave the gate standing.

    The out-of-tree leg is deliberately FIRST: it is pure path math, while the
    branch leg shells out. A write that is already out of tree never pays the
    subprocess.

    Sibling to `_is_smm_write`, and deliberately NOT merged with it — see the
    two-predicate note on the gate in run().
    """
    root = worktree.resolve_git_root(cwd)  # memoized per cwd
    if root is None:
        return False
    if _is_outside_tree(target_file, root, cwd):
        return True
    return branch_names.is_free_branch(identity.get_current_branch(cwd))


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
    # (.claude/plans/) except the question gate. See lead_gates._LEAD_GATES.
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
        is_smm_write = _is_smm_write(smm_dir, target_file, cwd)
        try:
            sprint_data = sprint_state.read_sprint_content(smm_dir)
        except (ValueError, OSError) as exc:
            # A bad read is not "no sprint". `load_sprint` RAISES on a corrupt /
            # schema-invalid / symlinked sprint.json, and letting that escape is
            # not a block but an ALLOW: the hook dies with a traceback and exits
            # 1, which PreToolUse treats as a NON-blocking error — every gate
            # below is skipped and the write lands. On the Write hot path an
            # unreadable sprint must fail CLOSED, exactly as the marker gates
            # above now do (lead_gates._unspawned_teammate_story_exists).
            #
            # SMM writes stay exempt, for the same reason they are exempt from
            # the schedule gate: sprint.json lives in the SMM dir, and a gate
            # that blocks the only tool that can repair the file it is choking on
            # is a gate with no recovery path. `sprint_cli create` (Bash) is the
            # documented repair, and this keeps the Write/Edit route open too.
            if not is_smm_write:
                raise _common.BlockedError(
                    f"sprint.json cannot be read ({exc}). Every sprint gate is "
                    "blind until it is repaired, so writes are blocked rather "
                    "than silently un-gated. Repair it (smm/sprint_cli.py create) "
                    "or restore it from backup, then retry.",
                    "Sprint state unreadable — gates cannot be evaluated.",
                ) from exc
            sprint_data = None

        # Schedule gate (state-derived, no marker). In the pre-promotion window
        # (scheduled stories exist, no story in motion) force /xp-schedule before
        # implementation writes. SMM writes exempt (plan files already excluded
        # above). The in-motion guard keeps the gate quiet through the
        # /xp-accept review + /xp-story-close window so review-cycle fixes to the
        # closing story aren't blocked. Self-clears the instant a frontier is
        # promoted to in-progress.
        #
        # Deliberately NOT in lead_gates, and it needs no teammate exemption: it
        # has no marker to arm it, and a teammate only exists once a frontier is
        # in motion — the very condition that makes this gate quiet — so a
        # teammate can never meet it.
        #
        # Being state-derived is NOT what keeps it out of the table. A marker
        # gate can be state-derived too, and the assign gate now is: it arms on
        # the marker and self-clears on lead_gates._LeadGate.active_when. Being
        # marker-FREE is what keeps it out. So a new gate with a marker belongs
        # in lead_gates._LEAD_GATES, with an active_when if anything but its own
        # demanded action can make it moot — never as a fourth hand-rolled `if`
        # here, which inherits neither the teammate exemption nor the hot path.
        #
        # TWO PREDICATES, NEVER UNIONED. The two exemptions
        # overlap in practice but justify themselves differently:
        # `is_smm_write` earns its keep by REPAIRABILITY (sprint.json lives in
        # the SMM dir), which is why the corrupt-sprint escape above reads it and
        # nothing else. Scope — "out of tree", "on a free branch" — says nothing
        # about repairability, so folding the two into one `is_exempt` would open
        # the write door on a free branch while every sprint gate is blind. Nor
        # is one a subset of the other: $SMM_DIR is an env var, so the SMM dir can
        # sit INSIDE the working tree. TestCorruptSprintKeepsThePredicatesApart
        # goes red on the union.
        #
        # ORDER IS THE MECHANISM. `is_smm_write` is pure path math and stays
        # EAGER (the corrupt branch needs it first). `_is_out_of_story_scope`
        # shells out to an uncached `git rev-parse`, so it stays LAZY and LAST:
        # Python short-circuits left to right, and the gate window is rare, so
        # the subprocess is paid only when the gate is about to fire.
        # TestScheduleGateBranchProbeCost goes red if this term moves.
        if (
            sprint_data is not None
            and schedule_gate_active_data(sprint_data)
            and not is_smm_write
            and not _is_out_of_story_scope(target_file, cwd)
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
