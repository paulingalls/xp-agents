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
import markers
import resolves_probe
import security
import worktree
from event_schema import (
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_RESOLVES,
)
from test_parsing import is_test_run, parse_test_results

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _resolve_lint_on_commit(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Run linter on committed files and resolve lint concerns for passing ones."""
    if not files:
        return

    import lint_check

    git_root = worktree.resolve_git_root(cwd) or cwd

    for file_path in files:
        normalized = worktree.normalize_path(file_path, cwd)
        config = lint_check.detect_linter_config(cwd, git_root, file_path=normalized)
        if config is None:
            continue
        linter_name, _ = config
        lint_output = lint_check.run_linter(linter_name, normalized, cwd=git_root)
        if lint_output is None:
            concerns.resolve_concerns(
                smm_dir,
                lambda c, n=normalized: concerns.lint_concern_matches(c, n),
                agent_id,
                "Lint concern resolved on commit",
                events=events,
                resolutions=resolutions,
            )


COMMIT_SIZE_THRESHOLD = 12


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


_GIT_PUSH_RE = re.compile(r"\bgit\s+push\b")


def _is_git_push(command: str) -> bool:
    """Detect git push commands."""
    return bool(_GIT_PUSH_RE.search(command))


def _session_end_checklist(smm_dir: Path) -> str | None:
    """Return session-end checklist nudge if issues found."""
    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    parts: list[str] = []
    unresolved = _common.count_unresolved_concerns(events)
    if unresolved:
        parts.append(
            f"{unresolved} unresolved concern(s) — review before ending session."
        )
    parts.append("Summarize what was accomplished this session for the user.")
    return "Session-end checklist: " + " ".join(parts)


def _resolve_story_id(
    smm_dir: Path,
    cwd: str,
    committed_files: list[str],
    sprint: dict | None = None,
) -> str | None:
    """Resolve story_id for a commit using three-tier attribution.

    Tier 1: Teammate with .story-assignment-{name} file.
    Tier 2: Solo sprint — single in-progress story, or the unique
            highest-overlap in-progress story by file domain. Ties
            (multiple stories with equal non-zero overlap) return None
            so cross-cutting commits aggregate at sprint level.
    Tier 3: Non-sprint / infrastructure — returns None.
    """
    import sprint_store
    import story_metrics

    name = identity.extract_worktree_name(cwd) or "main"
    assignment = worktree.story_assignment_path(smm_dir, name)
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

    if len(in_progress) == 1:
        return in_progress[0]["id"]

    best_id: str | None = None
    best_overlap = 0
    tied = False
    for story in in_progress:
        domain = story_metrics.extract_file_domain_paths(story.get("file_domain", []))
        if not domain:
            continue
        overlap = sum(
            1 for f in committed_files if story_metrics.file_matches_domain(f, domain)
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_id = story["id"]
            tied = False
        elif overlap == best_overlap and best_overlap > 0:
            tied = True
    return None if tied else best_id


_QR_WINDOW_CAP = 30


def _check_qr_linkage(events: list[dict], agent_id: str) -> str | None:
    """Return a warning if no quality-review status since previous commit.

    The backward scan for the previous commit is capped at _QR_WINDOW_CAP
    events.  When no commit is found (first commit or beyond cap), the
    forward scan starts from index 0 -- fail-open: an ancient QR event
    may suppress the warning.  Acceptable because this is an advisory
    nudge, not a commit gate.
    """
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
        if e.get("type") == _common.STATUS and _common.QUALITY_REVIEW_RE.search(
            e.get("content", "")
        ):
            return None

    return (
        "No quality review found since previous commit. "
        "Run /xp-quality-review before committing."
    )


def _handle_commit(
    smm_dir: Path, agent_id: str, cwd: str, response_text: str
) -> str | None:
    """Process a git commit response: record events, consume markers, nudge.

    parse_commit_message returns None on failed commits (pre-commit hook
    rejection, empty commit, etc.) since git only emits '[branch hash] msg'
    on success. When None, skip all post-commit side effects — otherwise a
    failed commit would wipe the security marker and reset the review cycle.
    """
    msg = commits.parse_commit_message(response_text)
    if not msg:
        return None

    committed_files = commits.get_committed_files(cwd)
    commit_hash = commits.get_head_commit_hash(cwd)
    code_file_count = sum(1 for f in committed_files if security.is_code_file(f))
    has_code = code_file_count > 0

    raw_body = commits.get_commit_message_body(cwd) or msg
    resolves, body = commits.extract_resolves_trailer(raw_body)
    body = re.sub(r"\n+\s*Co-Authored-By:.*$", "", body, flags=re.DOTALL).strip()

    metadata: dict = {"code_commit": has_code, "code_file_count": code_file_count}
    if commit_hash:
        metadata[METADATA_KEY_COMMIT_HASH] = commit_hash
    if resolves:
        metadata[METADATA_KEY_RESOLVES] = resolves

    import sprint_store

    sprint = sprint_store.load_sprint(smm_dir)

    story_id = _resolve_story_id(smm_dir, cwd, committed_files, sprint=sprint)
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

    candidates = resolves_probe.find_probe_candidates(
        smm_dir, committed_files, resolves, cwd, events=events, resolutions=resolutions
    )
    status_event = resolves_probe.build_probe_status_event(
        candidates, commit_hash, agent_id
    )
    if status_event:
        pending.append(status_event)

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

    _resolve_lint_on_commit(
        smm_dir, cwd, agent_id, committed_files, events=events, resolutions=resolutions
    )
    security.consume_security_triaged(smm_dir, agent_id)

    if commit_hash:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)

    qr_warning = _check_qr_linkage(events, agent_id)

    return qr_warning


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core bash_post_tool logic. Appends events, returns nudge or None."""
    if _common.is_xp_agent(input_data):
        return None

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

    # Git commit detection
    if security.is_git_commit(command):
        return _handle_commit(smm_dir, agent_id, cwd, response_text)

    # Git push detection — nudge session-end checklist
    if _is_git_push(command):
        return _session_end_checklist(smm_dir)

    # Test run detection
    framework = is_test_run(command)
    if framework:
        results = parse_test_results(response_text, framework)
        passed = results["passed"]
        failed = results["failed"]

        # If parser couldn't extract numbers (truncated output, wrong dir, etc.),
        # record a neutral status — we don't know if tests passed or failed
        if passed == 0 and failed == 0:
            content = f"Tests ran ({framework}) — counts not extracted"
        else:
            content = f"Tests: {passed} passed, {failed} failed ({framework})"

        status = _common.make_event(
            _common.STATUS,
            agent_id,
            content,
            working_on=[],
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
