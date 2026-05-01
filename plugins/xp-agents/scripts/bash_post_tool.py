#!/usr/bin/env python3
"""PostToolUse command hook for Bash: parse git commits and test results.

Records commit status events, checks commit size, and records test
pass/fail status. Nudges /simplify after commits with 3+ code files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import re

import _common
import commits
import concerns
import identity
import lint_resolution
import markers
import security
import worktree
from event_schema import (
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_RESOLVES,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    event_action,
)
from test_parsing import (
    PARSER_STATUS_PARSED,
    PARSER_STATUS_ZERO,
    is_test_run,
    parse_test_results,
)

COMMIT_SIZE_THRESHOLD = 12

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


# ---------------------------------------------------------------------------
# Commit handling
# ---------------------------------------------------------------------------


def _resolve_story_id(
    smm_dir: Path,
    cwd: str,
    committed_files: list[str],
    sprint: dict | None = None,
    message: str | None = None,
) -> str | None:
    """Resolve story_id for a commit using four-tier attribution.

    Tier 0: `[story-NNN]` prefix in commit message — authoritative when
            the named story is currently in-progress. Falls through when
            the prefix is absent or names a non-in-progress story.
    Tier 1: Teammate with .story-assignment-{name} file.
    Tier 2: Solo sprint — single in-progress story, or the unique
            highest-overlap in-progress story by file domain. Ties
            (multiple stories with equal non-zero overlap) return None
            so cross-cutting commits aggregate at sprint level.
    Tier 3: Non-sprint / infrastructure — returns None.
    """
    import sprint_store
    import story_metrics

    wt_name = identity.extract_worktree_name(cwd)
    if wt_name is not None:
        assignment = worktree.story_assignment_path(smm_dir, wt_name)
        try:
            story_id = assignment.read_text(encoding="utf-8").strip()
            if story_id:
                return story_id
        except (FileNotFoundError, OSError):
            pass

    if sprint is None:
        sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None

    in_progress = sprint_store.list_stories(sprint, status="in-progress")
    if not in_progress:
        return None

    if message:
        m = story_metrics.STORY_PREFIX_RE.match(message)
        if m:
            tagged = m.group(1)
            if any(s["id"] == tagged for s in in_progress):
                return tagged

    if len(in_progress) == 1:
        return in_progress[0]["id"]

    story_id, _ = story_metrics.resolve_dominant_story(in_progress, committed_files)
    return story_id


_QR_WINDOW_CAP = 30


def _check_qr_linkage(
    events: list[dict], agent_id: str, *, has_code: bool = True
) -> str | None:
    """Return a warning if no quality-review status since previous commit.

    The backward scan for the previous commit is capped at _QR_WINDOW_CAP
    events.  When no commit is found (first commit or beyond cap), the
    forward scan starts from index 0 -- fail-open: an ancient QR event
    may suppress the warning.  Acceptable because this is an advisory
    nudge, not a commit gate.

    `has_code=False` short-circuits the nudge for doc-only / config-only
    commits — /xp-quality-review only applies to code changes.
    """
    if not has_code:
        return None
    prev_commit_idx: int | None = None
    start = max(0, len(events) - _QR_WINDOW_CAP)
    for i in range(len(events) - 1, start - 1, -1):
        e = events[i]
        if e.get("type") == _common.COMMIT and e.get("agent_id") == agent_id:
            prev_commit_idx = i
            break

    search_start = (prev_commit_idx + 1) if prev_commit_idx is not None else 0
    for i in range(search_start, len(events)):
        e = events[i]
        if (
            e.get("type") == _common.STATUS
            and event_action(e) == STATUS_ACTION_QR_COMPLETE
        ):
            return None

    return (
        "No quality review found since previous commit. "
        "Run /xp-quality-review before committing."
    )


def _handle_commit(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    response_text: str,
    *,
    is_xp_agent_leak: bool = False,
) -> str | None:
    """Process a git commit response: record events, consume markers, nudge.

    parse_commit_message returns None on failed commits (pre-commit hook
    rejection, empty commit, etc.) since git only emits '[branch hash] msg'
    on success. When None, skip all post-commit side effects — otherwise a
    failed commit would wipe the security marker and reset the review cycle.

    is_xp_agent_leak: when True, only the commit event is recorded. Skips lint
    resolution, security-marker consumption, review-cycle reset, and the
    QR-warning return so a leaked subagent agent_type can't mutate state
    under a wrong identity (e.g. consume main's security marker).
    """
    msg = commits.parse_commit_message(response_text)
    if not msg:
        return None

    committed_files = commits.get_committed_files(cwd)
    commit_hash = commits.get_head_commit_hash(cwd)
    code_file_count = sum(1 for f in committed_files if security.is_code_file(f))
    has_code = code_file_count > 0

    raw_body = commits.get_commit_message_body(cwd) or msg
    resolves, body, has_trailer = commits.extract_resolves_trailer(raw_body)
    body = re.sub(r"\n+\s*Co-Authored-By:.*$", "", body, flags=re.DOTALL).strip()

    metadata: dict = {
        "action": STATUS_ACTION_COMMIT_SUCCESS,
        "code_commit": has_code,
        "code_file_count": code_file_count,
    }
    if commit_hash:
        metadata[METADATA_KEY_COMMIT_HASH] = commit_hash
    if resolves:
        metadata[METADATA_KEY_RESOLVES] = resolves
    if has_trailer:
        metadata["has_resolves_trailer"] = True

    import sprint_store

    sprint = sprint_store.load_sprint(smm_dir)

    story_id = _resolve_story_id(
        smm_dir, cwd, committed_files, sprint=sprint, message=body
    )
    if story_id:
        metadata["story_id"] = story_id
    if sprint is not None:
        metadata["sprint_id"] = sprint["sprint_id"]

    pending: list[dict] = [
        _common.make_event(
            _common.COMMIT,
            agent_id,
            body,
            files=committed_files,
            metadata=metadata,
        )
    ]

    events, resolutions = _common.load_events_with_resolutions(smm_dir)

    file_count = len(committed_files)
    if file_count >= COMMIT_SIZE_THRESHOLD:
        pending.append(
            _common.make_event(
                _common.CONCERN,
                agent_id,
                f"Commit touches {file_count} files — consider smaller commits.",
                severity="medium",
                files=committed_files,
            )
        )

    _common.bulk_append_safe(smm_dir, pending)

    if is_xp_agent_leak:
        return None

    lint_resolution.resolve_lint_on_commit(
        smm_dir, cwd, agent_id, committed_files, events=events, resolutions=resolutions
    )
    lint_resolution.sweep_orphan_lint_concerns(
        smm_dir, cwd, agent_id, committed_files, events=events, resolutions=resolutions
    )
    security.consume_security_triaged(smm_dir, agent_id)

    if commit_hash:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)

    return _check_qr_linkage(events, agent_id, has_code=has_code)


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
    if security.is_git_commit(command):
        is_xp_agent_leak = _common.is_xp_agent(input_data)
        result = _handle_commit(
            smm_dir,
            agent_id,
            cwd,
            response_text,
            is_xp_agent_leak=is_xp_agent_leak,
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

        if failed > 0:
            concern = _common.make_event(
                _common.CONCERN,
                agent_id,
                f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})",
                severity="high",
            )
            _common.append_safe(smm_dir, concern)
        elif failed == 0:
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
                        "(/simplify, /xp-quality-review, /xp-security-triage)."
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
