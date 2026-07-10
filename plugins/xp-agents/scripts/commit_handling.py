#!/usr/bin/env python3
"""Commit-handling block extracted from bash_post_tool.

Holds the post-commit pipeline (`_handle_commit`) and the TDD-red
test-only-commit detector (`_prior_commit_was_test_only`). Story
attribution (`_resolve_story_id`), the QR-linkage advisory
(`_check_qr_linkage`), the commit-event builder (`make_commit_event`),
and the concern recorders now live in the sibling `commit_event` module
(extracted to keep this file under the 500-line cap) and are re-exported
below so the historical `from commit_handling import ...` paths keep
working. bash_post_tool imports the entry points it actually calls in
`run()` — `_handle_commit` and `_prior_commit_was_test_only`.

The [verify-deferred] marker parsing + verify-path bookkeeping lives in the
sibling `verify_deferred` module (extracted to keep this file under the
500-line cap); `_handle_commit` reuses it for the post-commit debt event.
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
import resolution
from event_schema import METADATA_KEY_COMMIT_HASH
from pre_tool_write import is_test_file
from verify_deferred import (
    METADATA_KEY_VERIFY_DEFERRED,
    VERIFY_DEBT_CONTENT_LIMIT,
    parse_verify_deferred,
    untouched_paths_for_story,
)

_WATERMARK_ID = "bash-post-tool"

COMMIT_SIZE_THRESHOLD = 12


# -------------------------------------------------------------------
# Story/QR attribution + commit-event construction — re-exported from
# commit_event
# -------------------------------------------------------------------
# Bodies live in commit_event.py; this block keeps the historical
# `from commit_handling import make_commit_event` import path working,
# and `_handle_commit` below calls these through the module namespace.
from commit_event import (  # noqa: E402  intentional mid-file re-export
    _check_qr_linkage,
    _confirm_commit_repo,
    _record_unconfirmed_commit,
    _record_unlinkable_trailer,
    _resolve_story_id,
    make_commit_event,
)

# Public API contract — listed for pyright (so re-exports aren't flagged
# "not accessed") and ruff F401 suppression without per-line noqa. Must
# enumerate ALL public names of this module, both module-defined and
# re-exported, to be a complete contract.
__all__ = [
    "COMMIT_SIZE_THRESHOLD",
    "_check_qr_linkage",
    "_confirm_commit_repo",
    "_handle_commit",
    "_prior_commit_was_test_only",
    "_record_unconfirmed_commit",
    "_record_unlinkable_trailer",
    "_resolve_story_id",
    "make_commit_event",
]


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
    effective_cwd, raw_body = _confirm_commit_repo(
        command, cwd, response_text, scan_target=scan_target
    )
    if effective_cwd is None:
        # A rejected pre-commit also leaves HEAD unmatched, and that must stay
        # silent. Only speak up when the command named a repo we genuinely
        # could not inspect — a `-C` path hidden behind an unexpanded shell
        # variable. A literal `-C` path that doesn't exist is a git failure
        # (no commit anywhere), so dash_c_unreachable returns False for it.
        if commits.dash_c_unreachable(command):
            _record_unconfirmed_commit(smm_dir, command, agent_id)
        return None

    msg = commits.parse_commit_message(response_text)

    committed_files = commits.get_committed_files(effective_cwd)
    commit_hash = commits.get_head_commit_hash(effective_cwd)
    code_file_count = code_files.count_code_files(committed_files)
    has_code = code_file_count > 0

    # Dedupe by commit_hash: `_head_matches_command` only proves HEAD's
    # subject equals the `-m` arg. If HEAD didn't advance since the last
    # recorded commit (same-subject retry after a pre-commit reject), the
    # match is the *prior* commit, not a fresh one — skip to avoid a
    # duplicate event under a stale hash. parse_commit_message can also
    # echo a stale `[branch hash] msg` line (e.g. piped from prior output);
    # the same guard catches that.
    events, resolutions = _common.load_events_with_resolutions(smm_dir)
    if commit_hash and any(
        e.get("type") == _common.COMMIT
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    ):
        return None

    raw_body = raw_body or msg
    if not raw_body:
        return None
    resolves, body, has_trailer = commits.extract_resolves_trailer(raw_body)
    body = re.sub(r"\n+\s*Co-Authored-By:.*$", "", body, flags=re.DOTALL).strip()

    # A trailer naming an id absent from the live log resolves nothing.
    # `resolve_prefix` is a lookup over the events it is handed, so an archived
    # or mistyped target no-ops in silence. Record the commit either way — a
    # dangling id is harmless — but surface the ids that will not link.
    #
    # `known` must be the SAME index the resolver consults: top-level event ids
    # PLUS nested retrospective try-item ids (a trailer can close a retro Try).
    # Membership is an exact-id test: `extract_resolves_trailer` already
    # validated every id to exactly 12 hex (EVENT_ID_RE), and event ids are
    # exactly 12 hex too, so no id is ever a strict prefix of another — the
    # prefix-scan branch resolve_prefix keeps for short ids is unreachable here.
    if resolves:
        known = resolution.resolvable_event_ids(events)
        unknown = [rid for rid in resolves if rid not in known]
        if unknown:
            _record_unlinkable_trailer(smm_dir, agent_id, unknown)

    import branching
    import sprint_store

    sprint = sprint_store.load_sprint(smm_dir)

    story_id = _resolve_story_id(
        smm_dir, effective_cwd, committed_files, sprint=sprint, message=body
    )

    # Tag commits emitted on a free branch — honored by
    # retro_metrics._compute_resolves_link_rate as a conditional-include
    # filter (counts only when the commit carries a Resolves trailer).
    # get_current_branch returns "" on git failure; is_free_branch("") is
    # False (safe-fail: untagged commit drops into the denominator).
    is_free_session = branching.is_free_branch(
        identity.get_current_branch(effective_cwd)
    )

    # Stamp the active review cadence so retro metrics can tell a story-cadence
    # commit (review deferred to /xp-story-close) from a commit-cadence one.
    review_cadence = markers.read_review_cadence(smm_dir)

    pending: list[dict] = [
        make_commit_event(
            agent_id,
            body,
            commit_hash=commit_hash,
            files=committed_files,
            code_file_count=code_file_count,
            story_id=story_id,
            sprint_id=sprint["sprint_id"] if sprint is not None else None,
            resolves=resolves,
            has_resolves_trailer=has_trailer,
            is_free_session=is_free_session,
            review_cadence=review_cadence,
        )
    ]

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

    # Parse the trailer-stripped `body` (not raw_body): with re.DOTALL the
    # rationale capture would otherwise swallow the Resolves-Event /
    # Co-Authored-By trailers into the recorded debt content.
    rationale = parse_verify_deferred(body) if not is_xp_agent_leak else None
    if rationale is not None and story_id:
        deferred = untouched_paths_for_story(smm_dir, effective_cwd, story_id)
        if deferred:
            pending.append(
                _common.make_event(
                    _common.DEBT,
                    agent_id,
                    f"[verify-deferred] {rationale}"[:VERIFY_DEBT_CONTENT_LIMIT],
                    files=deferred,
                    metadata={
                        "story_id": story_id,
                        METADATA_KEY_VERIFY_DEFERRED: True,
                    },
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
