#!/usr/bin/env python3
"""PostToolUse command hook for Bash: parse git commits and test results.

Records commit status events, checks commit size, and records test
pass/fail status. Nudges to commit and run /xp-quality-review when a
green test run leaves code files uncommitted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import concerns
import git_commits
import hook_liveness
import identity
import markers
import run_attribution
import test_attribution
from commit_handling import (
    _handle_commit,
    _working_tree_is_test_only,
    is_tdd_red_step,
)
from event_metadata import (
    CONCERN_ACTION_TRANSIENT_TEST,
    METADATA_KEY_TEST_COUNT,
    METADATA_KEY_TEST_ERRORS,
)
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

CAPTURED_EXIT_ADVISORY = (
    "Test-failure gate left armed: this command's exit status is not the "
    "runner's. A command substitution, pipe, `;`, newline or `||` captured or "
    "discarded it, so a 0 here proves nothing about the suite. Re-run the "
    "runner where its own exit status becomes the command's — a leading `cd x "
    "&&` or a trailing `&& next` still counts — to clear open test-failure "
    "concerns."
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


def _green_run_signals(command: str) -> tuple[bool, bool]:
    """`(a test runner EXECUTED, the 0 we just saw is that runner's own)`.

    Both, from one call, because the success path asks them at two different
    places — the STATUS digest needs the second alone, the concern-resolving
    clear needs both — and they are the two independent ways a 0 lies. Deriving
    them twice would let the two un-gate legs drift apart, which is silent: the
    gate simply stops being armed.

    Clearing on either lie DISARMS the gate — the far worse direction, since
    attributing too little merely files a false concern.

    The runner never ran. `is_test_run` matches a runner NAME anywhere in the
    command, so a succeeding `grep -rn pytest src/` (grep exits 0 when it
    matches) resolved every open test-failure concern — a red suite un-gated by
    grepping for the word. `executed_framework` answers this by requiring the
    EXECUTABLE POSITION, deliberately not "the parser extracted counts": for a
    framework whose output the parser cannot read, the failing run writes an
    exit-code concern and the later passing run is equally unparseable, so a
    parser-status gate would deadlock.

    The runner ran, but the 0 is not its own. This one survived review behind a
    false premise — "exit 0 means every segment of a compound ran, so no
    corroboration is needed here". Every segment does run; only `&&` carries a
    segment's FAILURE out to the overall exit. Live evidence:
    `OUT=$(pytest tests/); echo $?` exited 0 with a pytest that exited 1, and
    this hook announced every prior failure resolved over a red suite.
    `exit_status_proves_runner_passed` answers this one — by shell structure, so
    the answer is the same in every language.
    """
    return (
        test_attribution.executed_framework(command) is not None,
        test_attribution.exit_status_proves_runner_passed(command),
    )


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core bash_post_tool logic. Appends events, returns nudge or None."""
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Ahead of every branch below (commit handling, test-run detection, the
    # ignored-command fallthrough): the write records that THIS hook ran, not
    # that this particular command mattered. Its own plain guard — not
    # `is_xp_agent_leak`, which is threaded into commit handling for a
    # different purpose and is only computed inside the commit branch.
    if not _common.is_xp_agent(input_data):
        hook_liveness.write_heartbeat(
            smm_dir, session_id=hook_liveness.payload_session_id(input_data)
        )

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
    # Single strip_quoted scan per Bash, threaded through is_git_commit and the
    # `-C` presence predicates below it (dash_c_unreachable, head_probe_target).
    # Avoids the re.DOTALL heredoc scan running twice on every commit-shaped
    # Bash. `parse_effective_cwd` is not one of them: it reads its own
    # offset-preserving mask, because a stripped scan deletes the path.
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
        # TDD red-step detection. `tdd_red` (working-tree test-only-dirty OR
        # a test-only prior commit) TAGS the event so work_signals doesn't
        # count deliberate reds as regressions in either workflow.
        #
        # The failed-test CONCERN below is gated on `tree_test_only` ONLY,
        # NOT the full `tdd_red`: `_prior_commit_was_test_only` stays True for
        # the WHOLE green phase in a commit-first workflow (the last commit is
        # still the test-only one until impl is committed), so gating the
        # concern on it would suppress a genuine green-phase failure and
        # un-arm the stop gate. The working-tree signal correctly clears the
        # moment impl code is in flight, so it is the honest concern gate.
        tree_test_only = _working_tree_is_test_only(cwd)
        tdd_red = is_tdd_red_step(smm_dir, cwd, tree_test_only=tree_test_only)
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
        }
        if tdd_red:
            metadata[METADATA_KEY_TDD_RED] = True
        # There are TWO ways a green run un-gates a red one — the resolution
        # below and this status — so both read one derivation of the same
        # signals.
        ran_a_runner, exit_proves_pass = _green_run_signals(command)
        if failed == 0 and not exit_proves_pass:
            # The status leg is the one easy to miss, because it un-gates with
            # no resolution event at all: `tdd_check.find_last_test_signal`
            # walks the log backwards and returns "pass" on the first
            # pass-shaped STATUS it meets, short-circuiting before it ever
            # reaches the open failure concern. This append sits OUTSIDE the
            # clear branch below, so gating only the clear leaves the digest
            # free to un-gate the suite on its own. A 0 we cannot attribute to
            # the runner is not a pass, and `test_passed` is dropped for the
            # same reason producers omit counts they do not have.
            content = f"Tests ran ({framework}) — runner exit status not observed"
            metadata["exit_status_captured"] = True
        elif parser_status == PARSER_STATUS_PARSED:
            content = f"Tests: {passed} passed, {failed} failed ({framework})"
            metadata["test_passed"] = failed == 0
            metadata[METADATA_KEY_TEST_COUNT] = passed + failed
            if errors > 0:
                metadata[METADATA_KEY_TEST_ERRORS] = errors
        elif parser_status == PARSER_STATUS_ZERO:
            content = f"Tests ran ({framework}) — 0 tests"
            metadata["test_passed"] = True
            metadata[METADATA_KEY_TEST_COUNT] = 0
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

        if failed > 0 and not tree_test_only:
            # Shared with bash_failure's degraded producer so the two cannot
            # drift on the keys or the omit-don't-fabricate rules; this caller
            # is the one that always has parsed counts.
            concern_metadata: dict = {
                "action": CONCERN_ACTION_TRANSIENT_TEST,
                **run_attribution.run_attribution_metadata(
                    input_data.get("cwd"),
                    failed=failed,
                    total=passed + failed,
                    errors=errors,
                ),
            }
            concern = _common.make_event(
                _common.CONCERN,
                agent_id,
                f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})",
                severity="high",
                metadata=concern_metadata,
            )
            _common.append_safe(smm_dir, concern)
        elif failed == 0 and ran_a_runner and exit_proves_pass:
            had_failures = _resolve_test_concerns(smm_dir, agent_id)

            # Nudge: commit after green if there are uncommitted code files
            if passed > 0:
                parts: list[str] = []
                if had_failures:
                    parts.append("All prior test failures resolved — tests are green.")
                # Under story cadence committing triggers no review — the
                # promise would be false. Cadence is tested first because it
                # is one marker read, while the uncommitted probe spawns git
                # subprocesses on every green test run.
                cadence = markers.read_review_cadence(smm_dir)
                if cadence != "story" and commits.get_uncommitted_code_files(cwd):
                    parts.append("Commit now to trigger /xp-quality-review.")
                if parts:
                    return " ".join(parts)
        elif failed == 0 and ran_a_runner:
            # A runner ran and reported nothing failing, but its exit status
            # never reached the shell — the only way to land here, since the
            # clear above differs from this branch in exactly that one term.
            # Refusing silently is an armed gate with no visible way out: the
            # agent sees neither the reason nor the fact that a plain re-run
            # clears it.
            return CAPTURED_EXIT_ADVISORY

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
