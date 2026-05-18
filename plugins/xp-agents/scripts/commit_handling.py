#!/usr/bin/env python3
"""Commit-handling block extracted from bash_post_tool.

Holds the post-commit pipeline (`_handle_commit`), story attribution
(`_resolve_story_id`), QR-linkage advisory (`_check_qr_linkage`), the
truncated-stdout fallback (`_head_matches_command`), and the TDD-red
test-only-commit detector (`_prior_commit_was_test_only`). bash_post_tool
imports the entry points it actually calls in `run()` —
`_handle_commit` and `_prior_commit_was_test_only`.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import code_files
import commits
import identity
import lint_resolution
import markers
import worktree
from event_schema import (
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_RESOLVES,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_QR_COMPLETE,
    event_action,
)
from pre_tool_write import is_test_file

_WATERMARK_ID = "bash-post-tool"

COMMIT_SIZE_THRESHOLD = 12


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


def _head_matches_command(command: str, head_body: str | None) -> bool:
    """True if the `-m` message in `command` matches HEAD's commit subject.

    Fallback when `parse_commit_message` can't see the commit success
    line. The `[branch hash] msg` line lives at the END of git's stdout,
    and heavy pre-commit hook chains can push total Bash output past the
    tool's truncation cap — slicing that line off. Comparing the `-m`
    argument against HEAD's actual body is the authoritative signal git
    itself leaves behind, so we don't need stdout to be intact.

    First lines only: pre-commit hooks may add trailers but rarely
    rewrite the subject. Stricter matching would miss real commits.
    """
    if not head_body:
        return False
    expected = commits.extract_commit_message(command)
    if not expected:
        return False
    expected_first = expected.strip().split("\n", 1)[0].strip()
    actual_first = head_body.strip().split("\n", 1)[0].strip()
    return bool(expected_first) and expected_first == actual_first


def _handle_commit(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    command: str,
    response_text: str,
    *,
    is_xp_agent_leak: bool = False,
    scan_target: str | None = None,
) -> str | None:
    """Process a git commit response: record events, consume markers, nudge.

    Commit-success signal: primary is `parse_commit_message` matching the
    `[branch hash] msg` line in stdout. Fallback when stdout is truncated
    (large pre-commit hooks): `_head_matches_command` confirms HEAD's body
    matches the `-m` arg we asked git to commit. Either signal proves the
    commit landed. When both fail (pre-commit rejection, empty commit,
    not-a-repo), skip all post-commit side effects — otherwise a failed
    commit would wipe the security marker and reset the review cycle.

    is_xp_agent_leak: when True, only the commit event is recorded. Skips lint
    resolution, security-marker consumption, review-cycle reset, and the
    QR-warning return so a leaked subagent agent_type can't mutate state
    under a wrong identity (e.g. consume main's security marker).

    `command` is parsed for `cd <wt>` / `git -C <wt>` segments so the
    HEAD/files/body lookups target the repo the commit actually ran in,
    not the orchestrator cwd left after a `cd -` cleanup. `scan_target`
    is the pre-stripped command from `run` — passing it through avoids
    a second strip_quoted scan inside parse_effective_cwd.
    """
    effective_cwd = commits.parse_effective_cwd(command, cwd, scan_target=scan_target)

    raw_body = commits.get_commit_message_body(effective_cwd)

    msg = commits.parse_commit_message(response_text)
    if not msg and not _head_matches_command(command, raw_body):
        return None

    committed_files = commits.get_committed_files(effective_cwd)
    commit_hash = commits.get_head_commit_hash(effective_cwd)
    code_file_count = sum(1 for f in committed_files if code_files.is_code_file(f))
    has_code = code_file_count > 0

    raw_body = raw_body or msg
    if not raw_body:
        return None
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
        smm_dir, effective_cwd, committed_files, sprint=sprint, message=body
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
        smm_dir,
        effective_cwd,
        agent_id,
        committed_files,
        events=events,
        resolutions=resolutions,
    )
    lint_resolution.sweep_orphan_lint_concerns(
        smm_dir,
        effective_cwd,
        agent_id,
        committed_files,
        events=events,
        resolutions=resolutions,
    )

    if commit_hash:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)

    return _check_qr_linkage(events, agent_id, has_code=has_code)


def _prior_commit_was_test_only(smm_dir: Path) -> bool:
    """True iff the most recent commit event in events.jsonl committed
    only test-layer files (per pre_tool_write.is_test_file — includes
    test_*.py, tests/ paths, and test infrastructure like conftest.py).
    Used to tag test_run_complete events so consecutive_failures
    skips runs where the agent is iterating in the test layer (the
    canonical RED step in TDD plus adjacent test-infra work). Empty
    file lists or a missing prior commit return False — defaulting to
    "treat failures as regressions" is honest about what we don't know.
    """
    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    for e in reversed(events):
        if e.get("type") != _common.COMMIT:
            continue
        files = e.get("files") or []
        if not files:
            return False
        return all(is_test_file(f) for f in files)
    return False
