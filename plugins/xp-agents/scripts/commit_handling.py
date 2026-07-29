#!/usr/bin/env python3
"""Commit-handling block extracted from bash_post_tool.

Holds the post-commit pipeline (`_handle_commit`) and the TDD-red-step
detector (`is_tdd_red_step`), which ORs two signals: the test-only-commit
detector (`_prior_commit_was_test_only`, commit-first workflow) and the
test-only-dirty-tree detector (`_working_tree_is_test_only`, the
red-green-commit workflow's red step, which happens BEFORE any commit
exists). Story attribution (`_resolve_story_id`), the QR-linkage advisory
(`_check_qr_linkage`), the commit-event builder (`make_commit_event`),
and the concern recorders now live in the sibling `commit_event` module
(extracted to keep this file under the 500-line cap) and are re-exported
below so the historical `from commit_handling import ...` paths keep
working. bash_post_tool imports the entry points it actually calls in
`run()` — `_handle_commit` and `is_tdd_red_step`.

The [verify-deferred] marker parsing + verify-path bookkeeping lives in the
sibling `verify_deferred` module (extracted to keep this file under the
500-line cap); `_handle_commit` reuses it for the post-commit debt event.

The body-to-event sequence itself (trailer extraction, Co-Authored-By strip,
unlinkable-trailer advisory, sprint load, story attribution, free-branch and
cadence tagging) lives in `commit_emit.build_commit_event` — a second caller
needs it verbatim, and copying it is how the merge emitter drifted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import code_files
import commit_command
import commit_emit
import commits
import lint_resolution
import markers
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
    _record_head_moved_trace,
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
    "_commit_hash_recorded",
    "_confirm_commit_repo",
    "_handle_commit",
    "_head_trace_recorded",
    "_prior_commit_was_test_only",
    "_record_head_moved_trace",
    "_record_unconfirmed_commit",
    "_record_unlinkable_trailer",
    "_resolve_story_id",
    "_working_tree_is_test_only",
    "is_tdd_red_step",
    "make_commit_event",
]


def _commit_hash_recorded(events: list[dict], commit_hash: str) -> bool:
    """True if a COMMIT event already carries `commit_hash` in its metadata.

    Shared by the success-path dedup guard and the HEAD-moved disambiguator
    below — both need the same "have we already recorded this hash" check.
    """
    return any(
        e.get("type") == _common.COMMIT
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    )


def _head_trace_recorded(events: list[dict], commit_hash: str) -> bool:
    """True if a HEAD-moved trace CONCERN already carries `commit_hash`.

    Dedup guard: a commit-shaped command that keeps failing to confirm while
    HEAD sits at the same unrecorded commit (repeated pre-commit re-runs after
    a rejection) must not append an identical trace every time. Keyed on the
    hash `_record_head_moved_trace` stamps into the concern metadata for
    exactly this purpose. Only the HEAD-moved trace carries a commit_hash on a
    CONCERN, so the type filter is enough to keep it apart from a COMMIT event.
    """
    return any(
        e.get("type") == _common.CONCERN
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    )


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
        if commits.dash_c_unreachable(command, scan_target=scan_target):
            _record_unconfirmed_commit(smm_dir, command, agent_id)
            return None
        # Repo was reachable, but HEAD's subject didn't match and stdout carried
        # no success line. Disambiguate a rejected pre-commit (HEAD unchanged)
        # from an unparsed success (HEAD advanced): probe HEAD from the repo the
        # command actually targeted. head_probe_target reads an explicit
        # `git -C <path>` (the CI-identity `git -c k=v -C <path>` form included)
        # and returns None for a nonexistent target — git aborts and lands
        # nothing, so the orchestrator's unrelated HEAD is never misread. A
        # reachable `-C` whose landed commit had its message rewritten is probed
        # in its own repo instead of being blanket-suppressed.
        probe_cwd = commit_command.head_probe_target(
            command, cwd, scan_target=scan_target
        )
        if probe_cwd is None:
            return None
        head = commits.get_head_commit_hash(probe_cwd)
        if head:
            events, _ = _common.load_events_with_resolutions(smm_dir)
            if not _commit_hash_recorded(events, head):
                # Try to rebuild the event git can still prove, so a
                # Resolves-Event trailer on this commit is not silently
                # dropped. The trace is the fallback for the cases the
                # rebuild will not claim (ambiguous HEAD, unreadable body) —
                # one observation per commit, never both. The rebuild is
                # gated on the commit-hash dedup ALONE: a hash that already
                # carries a trace, from an earlier attempt whose body read
                # failed, must stay rebuildable.
                rebuilt = commit_emit.rebuild_at_head(
                    smm_dir,
                    agent_id,
                    probe_cwd,
                    command,
                    head,
                    events=events,
                    is_xp_agent_leak=is_xp_agent_leak,
                )
                if not rebuilt and not _head_trace_recorded(events, head):
                    _record_head_moved_trace(smm_dir, command, agent_id, head)
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
    if commit_hash and _commit_hash_recorded(events, commit_hash):
        return None

    # Stamp the active review cadence so retro metrics can tell a story-cadence
    # commit (review deferred to /xp-story-close) from a commit-cadence one.
    # Read here rather than inside the builder: `_check_qr_linkage` below needs
    # the same value, and one read serves both.
    review_cadence = markers.read_review_cadence(smm_dir)

    event = commit_emit.build_commit_event(
        smm_dir,
        agent_id,
        effective_cwd,
        raw_body or msg,
        commit_hash,
        events=events,
        committed_files=committed_files,
        code_file_count=code_file_count,
        review_cadence=review_cadence,
    )
    if event is None:
        return None

    pending: list[dict] = [event]

    # `story_id` is what the builder already derived and stored on the event, so
    # it is read back off it. `body` is NOT: `make_event` strips a trailing
    # `[refs: <id>]` span from `content` and routes its ids, so the stored
    # content is a derived value. The verify-deferred block below needs the
    # body the builder parsed, which is what `parse_commit_body` returns.
    body = commit_emit.parse_commit_body(raw_body or msg)[1]
    story_id = event["metadata"].get("story_id")

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

    return _check_qr_linkage(
        events, agent_id, has_code=has_code, cadence=review_cadence
    )


def _working_tree_is_test_only(cwd: str) -> bool:
    """True iff the working tree is dirty with test files ONLY — the
    canonical TDD red step, BEFORE the post-green commit exists.

    ``get_uncommitted_files`` is the wide "what code is in flight" signal:
    staged + unstaged + untracked, test files included. Test-only means it
    is non-empty AND every file in it is a test file — any non-test code
    file in flight means a failure could be a real regression, not a
    deliberate red step. It must be measured off this single wide scan:
    ``get_uncommitted_code_files`` omits untracked files, so a brand-new
    (never ``git add``ed) production file would slip past it and a genuine
    green-phase failure would be silently suppressed.

    None or [] from ``get_uncommitted_files`` (git timeout or no repo)
    returns False — fail safe, same default as
    ``_prior_commit_was_test_only``.
    """
    files = commits.get_uncommitted_files(cwd)
    if not files:
        return False
    return all(is_test_file(f) for f in files)


def is_tdd_red_step(
    smm_dir: Path, cwd: str, *, tree_test_only: bool | None = None
) -> bool:
    """True iff this is a deliberate TDD red step, by either signal:

    - the working tree is currently test-only-dirty (the red step BEFORE
      the mandated red-green-commit lands), or
    - the most recent commit was test-only (a commit-first red step,
      distinct workflow, preserved as-is).

    Used by bash_post_tool to TAG the test_run_complete event so a
    deliberate red is not counted as a regression streak by work_signals.
    (The failed-test concern itself gates on the working-tree signal
    ALONE — see bash_post_tool — because a commit-first prior-commit
    signal stays True through the whole green phase.)

    Pass `tree_test_only` when the caller already computed the working-tree
    signal for its own use (bash_post_tool needs it for the concern gate),
    so it is not re-shelled here.
    """
    if tree_test_only is None:
        tree_test_only = _working_tree_is_test_only(cwd)
    return _prior_commit_was_test_only(smm_dir) or tree_test_only


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
