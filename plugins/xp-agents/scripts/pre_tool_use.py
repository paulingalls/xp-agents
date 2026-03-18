#!/usr/bin/env python3
"""PreToolUse command hook: conflict prevention, debt injection, TDD tracking.

Fires on every tool call. Checks for working_on overlap via coordination file,
injects file-specific debt context for write tools, and nudges TDD ordering.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


# ---------------------------------------------------------------------------
# Git push detection
# ---------------------------------------------------------------------------


def is_git_push(command: str) -> bool:
    """Detect git push in a shell command using argv parsing.

    Handles /usr/bin/git, git -c key=val push, env git push, etc.
    Falls back to regex on parse failure.
    """
    import shlex

    try:
        tokens = shlex.split(command)
    except ValueError:
        # Malformed shell quoting — fall back to simple regex
        return bool(re.search(r"\bgit\s+push\b", command))

    # Walk tokens looking for a git executable followed by push subcommand
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Check if token is 'git' or ends with '/git'
        if tok == "git" or tok.endswith("/git"):
            # Scan forward past flags/options for the subcommand
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 1
                # Skip flag value for -c/-C style options
                prev = tokens[j - 1]
                if (
                    j < len(tokens)
                    and not prev.startswith("--")
                    and prev in ("-c", "-C")
                ):
                    j += 1
            if j < len(tokens) and tokens[j] == "push":
                return True
        i += 1
    return False


# ---------------------------------------------------------------------------
# Target file extraction
# ---------------------------------------------------------------------------


def get_target_file(tool_name: str, tool_input: dict) -> str | None:
    """Extract the target file path from tool_input, if applicable."""
    return _common.extract_file_path(tool_name, tool_input)


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
    coordination = _common.read_coordination(smm_dir)
    normalized_target = _common.normalize_path(file_path, cwd)

    for aid, entry in coordination.items():
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

    # Load enforcement mode (used by push gate, etc.)
    enforcement = _common.load_enforcement_mode()

    parts: list[str] = []

    # Push gate: block git push until security review has been run
    if tool_name == "Bash" and smm_dir is not None:
        command = tool_input.get("command", "")
        if is_git_push(command):
            head_hash = _common.get_head_hash(cwd)
            if head_hash is not None and not _common.security_tracker_exists(
                smm_dir, head_hash
            ):
                # Check if a previous review can carry forward
                # (only non-code changes since last reviewed commit)
                reviewed_hash = _common.find_last_reviewed_hash(smm_dir)
                if reviewed_hash is not None and not _common.diff_has_code_changes(
                    reviewed_hash, head_hash, cwd
                ):
                    # Carry forward: only non-code changes since last review
                    _common.write_security_tracker(smm_dir, head_hash)
                else:
                    # Block and request review — tracker will be written
                    # by security_review_done.py PostToolUse:Skill hook
                    # when /security-review completes
                    event = _common.make_event(
                        _common.SECURITY_REVIEW_REQUESTED,
                        agent_id,
                        f"Security review required before push (HEAD: {head_hash})",
                    )
                    _common.append_safe(smm_dir, event)
                    msg = (
                        "Security review required before pushing. "
                        "Either run the /security-review skill to "
                        "perform the review, or if you have already "
                        "reviewed the code, run the /security-clear "
                        "skill to clear the gate."
                    )
                    if enforcement == _common.ENFORCEMENT_ADVISORY:
                        parts.append(f"⚠️ Advisory warning: {msg}")
                    else:
                        raise _common.BlockedError(msg)

    target_file = get_target_file(tool_name, tool_input)

    # Conflict detection via .coordination.json (O(1), no event log scan)
    if target_file and smm_dir:
        conflict = check_working_on_overlap(smm_dir, agent_id, target_file, cwd)
        if conflict:
            if enforcement == _common.ENFORCEMENT_ADVISORY:
                parts.append(f"⚠️ Advisory warning: {conflict}")
            else:
                raise _common.BlockedError(conflict)

    # Debt injection for write tools
    events: list[dict] | None = None
    if target_file and smm_dir and tool_name in _WRITE_TOOLS:
        events = _common.read_events_raw(smm_dir)
        debts = _common.find_debt_for_file(events, target_file, cwd)
        if debts:
            debt_lines = ["<smm-debt-context>"]
            debt_lines.append(
                "Technical Debt for this file (informational, not instructions):"
            )
            for d in debts:
                debt_lines.append(f"- {d.get('content', '')} [{d.get('id', '')[:8]}]")
            debt_lines.append("</smm-debt-context>")
            parts.append("\n".join(debt_lines))

    # Plan review gate — nudge review before implementing an unreviewed plan
    if tool_name in _WRITE_TOOLS and smm_dir:
        if events is None:
            events = _common.read_events_raw(smm_dir)
        has_unreviewed_plan = False
        for e in reversed(events):
            content = e.get("content", "")
            if "plan_reviewed:" in content:
                break
            if "plan_awaiting_review:" in content:
                has_unreviewed_plan = True
                break
        if has_unreviewed_plan:
            parts.append(
                "Run /xp-plan-reviewer to review the plan before implementing."
            )

    # TDD order check
    if target_file and smm_dir:
        tdd_nudge = check_tdd_order(smm_dir, agent_id, target_file, tool_name)
        if tdd_nudge:
            parts.append(tdd_nudge)

    # Enforcement indicator (also emitted by session_start.py to survive compaction)
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
