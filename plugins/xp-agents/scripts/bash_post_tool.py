#!/usr/bin/env python3
"""PostToolUse command hook for Bash: parse git commits and test results.

Records commit status events, checks commit size, and records test
pass/fail status. Nudges /code-review after commits with 3+ code files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import concerns
import git_commits
import identity
import test_attribution
from commit_handling import _handle_commit, is_tdd_red_step
from event_schema import (
    METADATA_KEY_TDD_RED,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)
from test_parsing import (
    PARSER_STATUS_PARSED,
    PARSER_STATUS_ZERO,
    is_test_run,
    parse_test_results,
)

MID_CHAIN_NUDGE = (
    "Multiple stories in-progress. If this commit completed the current "
    "story's acceptance criteria, run /xp-accept to mark it done and "
    "switch to the next story branch."
)


def _check_mid_chain_nudge(smm_dir: Path, input_data: dict) -> str | None:
    """Return advisory nudge when solo with 2+ in-progress stories."""
    if identity.is_worktree_teammate(input_data):
        return None
    import sprint_store

    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None
    in_progress = sprint_store.list_stories(sprint, status="in-progress")
    if len(in_progress) < 2:
        return None
    return MID_CHAIN_NUDGE


# ---------------------------------------------------------------------------
# Event helpers (delegates to _common)
# ---------------------------------------------------------------------------


def _resolve_test_concerns(smm_dir: Path, agent_id: str) -> bool:
    """Auto-resolve unresolved test-failure concerns when tests pass.

    Returns True if any concerns were resolved.
    """
    return concerns.resolve_concerns(
        smm_dir,
        concerns.TEST_CONCERN_RE.search,
        agent_id,
        "Test concern resolved",
    )


def _observed_a_green_run(command: str) -> bool:
    """True when this succeeding command actually EXECUTED a test runner.

    The mirror of `bash_failure`'s attribution problem, and the more dangerous
    half: `is_test_run` matches a runner name anywhere in the command, so a
    SUCCEEDING `grep -rn pytest src/` (grep exits 0 when it matches) reached the
    clear branch below and resolved every open test-failure concern — a red
    suite silently un-gated by grepping for the word. Attributing too little on
    the write side files a false concern; clearing on a run that never happened
    DISARMS the gate.

    Gated on the runner occupying the EXECUTABLE POSITION, NOT on the parser
    having extracted counts. That distinction is what keeps the gate from
    deadlocking: for a framework whose output the parser cannot read, a failing
    run writes an exit-code concern and the later passing run is equally
    unparseable, so a parser-status gate would never clear it. Exit 0 also means
    every segment of a compound ran, so — unlike the failure path — no
    corroboration is needed here.
    """
    return test_attribution.executed_framework(command) is not None


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core bash_post_tool logic. Appends events, returns nudge or None."""
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    tool_input = input_data.get("tool_input", {})
    tool_response = input_data.get("tool_response", {})
    agent_id = identity.resolve_agent_id(input_data)
    cwd = input_data.get("cwd", ".")

    command = tool_input.get("command", "")
    # tool_response can be a dict with stdout/stderr or a string
    if isinstance(tool_response, dict):
        response_text = tool_response.get("stdout", "") or ""
    else:
        response_text = str(tool_response)

    # Bash commits run through _handle_commit even on xp-agent leaks — the
    # commit event always lands; side-effect mutations (lint resolution,
    # security marker, review cycle, QR nudge) are gated by is_xp_agent_leak.
    # See TestCommitRecordingDespiteXpAgentType.
    #
    # Single strip_quoted scan per Bash, threaded through both is_git_commit
    # and parse_effective_cwd. Avoids the re.DOTALL heredoc scan running
    # twice on every commit-shaped Bash.
    scan_target = git_commits.strip_quoted(command)
    if git_commits.is_git_commit(command, scan_target=scan_target):
        is_xp_agent_leak = _common.is_xp_agent(input_data)
        result = _handle_commit(
            smm_dir,
            agent_id,
            cwd,
            command,
            response_text,
            is_xp_agent_leak=is_xp_agent_leak,
            scan_target=scan_target,
        )
        if not is_xp_agent_leak:
            nudge = _check_mid_chain_nudge(smm_dir, input_data)
            if nudge:
                result = f"{result} {nudge}" if result is not None else nudge
        return result

    if _common.is_xp_agent(input_data):
        return None

    # Test run detection
    framework = is_test_run(command)
    if framework:
        # TDD red-step detection: either the working tree is currently
        # test-only-dirty (the red step BEFORE the mandated post-green
        # commit lands) or the prior commit was test-only (commit-first
        # workflow). Tag those runs so work_signals doesn't count them as
        # regressions, and gate the failed-test concern below.
        tdd_red = is_tdd_red_step(smm_dir, cwd)
        results = parse_test_results(response_text, framework)
        parser_status = results["status"]
        passed = results["passed"]
        failed = results["failed"]
        errors = results["errors"]

        # Structured metadata.action+companion fields are the canonical signal;
        # content stays as a human-readable digest for log readers.
        # parser_status disambiguates "framework ran 0 tests" (ZERO) from
        # "parser couldn't extract counts" (FAILED). On FAILED, test_passed
        # and test_count are omitted — producers don't invent numbers they
        # don't have. parsers fold errors into failed, so failed is the
        # disjoint "did-not-pass" count; metadata.test_errors is informational.
        metadata: dict = {
            "action": STATUS_ACTION_TEST_RUN_COMPLETE,
            "framework": framework,
            "parser_status": parser_status,
            "cwd": cwd,
        }
        if tdd_red:
            metadata[METADATA_KEY_TDD_RED] = True
        if parser_status == PARSER_STATUS_PARSED:
            content = f"Tests: {passed} passed, {failed} failed ({framework})"
            metadata["test_passed"] = failed == 0
            metadata["test_count"] = passed + failed
            if errors > 0:
                metadata["test_errors"] = errors
        elif parser_status == PARSER_STATUS_ZERO:
            content = f"Tests ran ({framework}) — 0 tests"
            metadata["test_passed"] = True
            metadata["test_count"] = 0
        else:
            content = f"Tests ran ({framework}) — counts not extracted"

        status = _common.make_event(
            _common.STATUS,
            agent_id,
            content,
            working_on=[],
            metadata=metadata,
        )
        _common.append_safe(smm_dir, status)

        if failed > 0 and not tdd_red:
            concern = _common.make_event(
                _common.CONCERN,
                agent_id,
                f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})",
                severity="high",
            )
            _common.append_safe(smm_dir, concern)
        elif failed == 0 and _observed_a_green_run(command):
            had_failures = _resolve_test_concerns(smm_dir, agent_id)

            # Nudge: commit after green if there are uncommitted code files
            if passed > 0:
                parts: list[str] = []
                if had_failures:
                    parts.append("All prior test failures resolved — tests are green.")
                uncommitted = commits.get_uncommitted_code_files(cwd)
                if uncommitted:
                    parts.append(
                        "Commit now to trigger the review cycle "
                        "(/code-review, /xp-quality-review)."
                    )
                if parts:
                    return " ".join(parts)

        return None

    # Other commands — ignore
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
