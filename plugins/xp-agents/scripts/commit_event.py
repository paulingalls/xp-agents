#!/usr/bin/env python3
"""Commit-event construction and story/QR attribution.

Extracted from commit_handling.py to stay under the 500-line cap. Holds
story attribution (`_resolve_story_id`), QR-linkage advisory
(`_check_qr_linkage`), the truncated-stdout fallback
(`_head_matches_command`), commit-repo confirmation
(`_confirm_commit_repo`), the unconfirmed-commit / unlinkable-trailer
concern recorders, and the shared commit-event builder
(`make_commit_event`). `_handle_commit` in commit_handling.py is the
sole in-repo caller of these.
"""

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import concerns
import identity
import markers
import worktree
from event_schema import (
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_RESOLVES,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_QR_COMPLETE,
    event_action,
)


def recorded_commit_hashes(events: list[dict]) -> set[str]:
    """Every commit hash the LIVE log already carries a commit event for.

    One home for the index, because three callers now dedup against it and each
    hand-rolled the same `(e.get("metadata") or {}).get("commit_hash")` walk:
    `commit_emit.merge_resolves` (which trailers a merge may re-derive) and
    `commit_observer` (which commits in a range still need recording). A fourth
    copy is how these drift, and drift here is silent — a missed entry
    re-records a commit, a spurious one drops it.

    LIVE log only, and the bound is real: compaction archives commit events once
    their sprint leaves the retention window, and a rebased branch's hashes
    never match. Callers must treat "absent" as "not visible from here", not as
    proof the commit was never recorded.
    """
    return {
        h
        for e in events
        if e.get("type") == _common.COMMIT
        for h in [(e.get("metadata") or {}).get(METADATA_KEY_COMMIT_HASH)]
        if h
    }


def _resolve_story_id(
    smm_dir: Path,
    cwd: str,
    committed_files: list[str],
    sprint: dict | None = None,
    message: str | None = None,
) -> str | None:
    """Resolve story_id for a commit using four-tier attribution.

    Tier 0: `[story-NNN]` prefix in commit message — authoritative when
            the named story is *in motion* (in-progress, reviewing, or
            closing). Honoring the closing/reviewing states is what keeps
            story-cadence review-fix commits (authored during
            /xp-story-close Step 4.5b, when the story has left in-progress)
            attributed instead of dropped. Falls through when the prefix is
            absent or names a non-in-motion (done/deferred) story — a likely
            stale tag.
    Tier 1: Teammate with .story-assignment-{name} file.
    Tier 2: Solo sprint — single in-progress story, or the unique
            highest-overlap in-progress story by file domain. Ties
            (multiple stories with equal non-zero overlap) return None
            so cross-cutting commits aggregate at sprint level.
    Tier 2.5: No story in-progress but exactly one in motion
            (closing/reviewing) — attribute an UNPREFIXED commit to it.
            Recovers prefix-less story-cadence review fixes authored during
            /xp-story-close. A bracket-tagged message (stale `[story-NNN]`,
            `[sprint-*]`, `[release]`, ...) is left to aggregate at sprint
            level rather than guessed.
    Tier 3: Non-sprint / infrastructure — returns None.
    """
    import sprint_status
    import sprint_store
    import story_metrics

    wt_name = identity.extract_worktree_name(cwd)
    if wt_name is None:
        # In-place (solo-delegation) teammate: its cwd IS the main checkout,
        # so there is no worktree path marker — but spawn_teammate exported
        # XP_TEAMMATE_NAME and wrote a name-keyed .story-assignment. Recover the
        # name from the env so attribution stays EXPLICIT (Tier 1) instead of
        # falling through to the single-in-progress heuristic, which would
        # mis-attribute when a second story is also in-progress.
        #
        # XP_TEAMMATE_NAME is a documented leaky var, so the env alone isn't
        # trustworthy: were it to leak into the lead AND a stale name-keyed
        # .story-assignment still exist, the lead's own commit would be
        # mis-attributed. `identity.in_place_teammate_name` — the shared helper
        # that also backs is_worktree_teammate, tdd_check._reader_scope, and
        # pre_tool_skill._is_live_teammate — gates on the lifetime-scoped
        # in-place marker spawn_teammate writes only WHILE the in-place child
        # runs; a leaked env with no live marker returns None and falls through
        # to the heuristics instead. Passing the already-validated `smm_dir`
        # keeps attribution keyed to the SAME SMM this commit is recorded in.
        wt_name = identity.in_place_teammate_name(smm_dir)
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

    # Tier 0: explicit prefix wins for any in-motion story. Checked before
    # the in-progress gate so a closing/reviewing story (no story is
    # in-progress during its close) keeps its tagged review commits.
    if message:
        m = story_metrics.STORY_PREFIX_RE.match(message)
        if m:
            tagged = m.group(1)
            in_motion = sprint_status.select_in_motion_stories(sprint["stories"])
            if any(s["id"] == tagged for s in in_motion):
                return tagged

    in_progress = sprint_store.list_stories(sprint, status="in-progress")
    if not in_progress:
        # Tier 2.5: no story in-progress, but work is still being committed —
        # e.g. story-cadence review fixes authored during /xp-story-close,
        # when the lone active story has moved to `closing`/`reviewing`.
        # Attribute an UNPREFIXED commit to the single in-motion story so it
        # isn't dropped from per-story metrics. A bracket-tagged message
        # (`[story-NNN]` stale, `[sprint-*]`, `[release]`, ...) is an explicit
        # signal — respect it and aggregate at sprint level instead of guessing.
        if message and story_metrics.BRACKET_PREFIX_RE.match(message):
            return None
        in_motion = sprint_status.select_in_motion_stories(sprint["stories"])
        if len(in_motion) == 1:
            return in_motion[0]["id"]
        return None

    if len(in_progress) == 1:
        return in_progress[0]["id"]

    story_id, _ = story_metrics.resolve_dominant_story(in_progress, committed_files)
    return story_id


_QR_WINDOW_CAP = 30


def _check_qr_linkage(
    events: list[dict],
    agent_id: str,
    *,
    has_code: bool = True,
    cadence: str = markers.DEFAULT_CADENCE,
) -> str | None:
    """Return a warning if no quality-review status since previous commit.

    The backward scan for the previous commit is capped at _QR_WINDOW_CAP
    events.  When no commit is found (first commit or beyond cap), the
    forward scan starts from index 0 -- fail-open: an ancient QR event
    may suppress the warning.  Acceptable because this is an advisory
    nudge, not a commit gate.

    `has_code=False` short-circuits the nudge for doc-only / config-only
    commits — /xp-quality-review only applies to code changes.

    `cadence="story"` also short-circuits: under story cadence, per-commit
    review is deliberately deferred to /xp-story-close (announced by
    pre_tool_bash.py's PreToolUse advisory), so demanding it here would
    contradict that deferral. Silence, not a second deferral message — the
    nudge exists to catch a *missing* per-commit review, and under story
    cadence there is no per-commit review to miss.
    """
    if not has_code:
        return None
    if cadence == "story":
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


def _confirm_commit_repo(
    command: str,
    cwd: str,
    response_text: str,
    *,
    scan_target: str | None = None,
) -> tuple[str | None, str]:
    """Return `(repo, head_body)` for the repo the commit actually landed in.

    Confirmation is by matching, not parsing: each candidate repo's HEAD
    subject is compared against the message the command supplied. That single
    mechanism covers all three ways the old gate failed — `-q` (no stdout
    signal), `-F -` (message on stdin), and `git -C "$VAR"` (path hidden behind
    a shell variable `strip_quoted` deletes, so the parse yields the wrong
    repo). `(None, "")` means no candidate holds this commit.
    """
    first: str | None = None
    first_body: str = ""
    for candidate in commits.commit_repo_candidates(
        command, cwd, scan_target=scan_target
    ):
        head_body = commits.get_commit_message_body(candidate) or ""
        if first is None:
            first = candidate
            first_body = head_body
        if _head_matches_command(command, head_body):
            return candidate, head_body

    # git's own `[branch hash] subject` line proves a commit landed even when
    # the message is unrecoverable from the command (e.g. `-F <tmpfile>` the
    # shell already deleted). Trust the first candidate in that case only —
    # reusing the body already fetched for it in the loop above (no second
    # `git log` subprocess on this PostToolUse hot path).
    if first is not None and commits.parse_commit_message(response_text):
        return first, first_body
    return None, ""


def _record_unconfirmed_commit(smm_dir: Path, command: str, agent_id: str) -> None:
    """A commit we could not inspect leaves a trace, not silence.

    Fires only when the command named a repo the hook could not reach, so a
    rejected pre-commit (HEAD legitimately unchanged) stays quiet. Without
    this, such a commit never enters the event log and any resolution trailer
    on it silently resolves nothing — an absence with no signal at all.
    Never raise: a hook must not break the user's commit.
    """
    first_line = command.strip().split("\n", 1)[0][:120]
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(
            smm_dir,
            concerns.make_concern(
                "Detected a git commit but could not confirm which repository it "
                f"landed in; no commit event recorded. Command: {first_line}",
                "low",
                agent_id,
            ),
        )


def _record_head_moved_trace(
    smm_dir: Path, command: str, agent_id: str, commit_hash: str
) -> None:
    """A commit-shaped command was issued and HEAD now points at a commit with
    no recorded event, and the rebuild would not claim it either. State the
    observation and NO cause: this fires for an unparsed success, for a
    backgrounded launch whose command has not run yet, and, rarely, for a
    rejection atop un-recorded history. None of them is called a landed commit.

    `commit_hash` (the HEAD the probe read) is stamped into the concern
    metadata so `_head_trace_recorded` can dedup repeated runs that fail to
    confirm while HEAD stays put — otherwise every retried pre-commit rejection
    appends another identical trace.
    Never raise: a hook must not break the user's commit.
    """
    first_line = command.strip().split("\n", 1)[0][:120]
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(
            smm_dir,
            concerns.make_concern(
                "A git commit command was issued and HEAD points at a commit "
                f"with no recorded event. Command: {first_line}",
                "low",
                agent_id,
                metadata={METADATA_KEY_COMMIT_HASH: commit_hash},
            ),
        )


def _record_unlinkable_trailer(
    smm_dir: Path, agent_id: str, unknown_ids: list[str]
) -> None:
    """A `Resolves-Event:` id absent from the live log links to nothing.

    Three causes, and the hook cannot tell them apart — it sees only the live
    log, not the archive. Say so plainly rather than assert the link was lost:
    the most common cause is benign (the target was resolved, then compacted).
    """
    ids = ", ".join(unknown_ids)
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(
            smm_dir,
            concerns.make_concern(
                f"Resolves-Event trailer names {ids}, absent from the live event "
                "log. Either the target was already resolved and compacted away "
                "(benign), or it aged out unresolved, or the id is mistyped. The "
                "link will not resolve.",
                "low",
                agent_id,
            ),
        )


def make_commit_event(
    agent_id: str,
    body: str,
    *,
    commit_hash: str | None,
    files: list[str],
    code_file_count: int,
    story_id: str | None = None,
    sprint_id: str | None = None,
    resolves: list[str] | None = None,
    has_resolves_trailer: bool = False,
    is_merge: bool = False,
    is_free_session: bool = False,
    review_cadence: str | None = None,
) -> dict:
    """Build a type=commit event from the shared metadata shape.

    Single canonical builder for every emitter: regular `git commit`
    (``_handle_commit``), the HEAD rebuild (``commit_emit.rebuild_at_head``),
    and close-cycle merges (``merge_commit_event``). When any of them adds a
    metadata field, this builder is the one place to update — eliminates the
    drift risk parallel builders would carry.

    Optional kwargs:
      - ``resolves`` / ``has_resolves_trailer``: bash-commit only
        (parsed from the commit message body)
      - ``is_merge``: ANY merge HEAD — >1 parent. Set by the close cycle and,
        since the hook routes converged, by every recorded merge on them. It
        does NOT mean "a story shipped"; `story_metrics` needs the close
        emitter's agent id for that.
        — excludes the event from ``retro_metrics._compute_resolves_link_rate``
        denominator so a merge HEAD doesn't dilute the rate without a trailer
      - ``is_free_session``: commit emitted on a free branch
        (``branching.is_free_branch(...)`` True). Honored by
        ``retro_metrics`` as a CONDITIONAL exclusion — the commit drops
        out of the rate ONLY when it carries no trailer (exploration);
        a free commit with a trailer counts both ways (rewards the
        voluntary fix-and-link behavior visibly).
      - ``review_cadence``: the session review cadence at commit time
        (``"commit"`` | ``"story"``). Only ``"story"`` is stamped (the
        non-default), mirroring ``is_free_session``; ``honesty_signals``
        exempts story-cadence commits from ``review_required_commits``
        since their review defers to ``/xp-story-close``.

    Callers pass ``code_file_count`` already computed (both sites
    compute it earlier for their own thresholds — recomputing here
    would duplicate the scan).
    """
    metadata: dict = {
        "action": STATUS_ACTION_COMMIT_SUCCESS,
        "code_commit": code_file_count > 0,
        "code_file_count": code_file_count,
    }
    if commit_hash:
        metadata[METADATA_KEY_COMMIT_HASH] = commit_hash
    if resolves:
        metadata[METADATA_KEY_RESOLVES] = resolves
    if has_resolves_trailer:
        metadata["has_resolves_trailer"] = True
    if story_id:
        metadata["story_id"] = story_id
    # `is not None` (not truthy): mirrors the pre-extraction
    # `if sprint is not None: metadata["sprint_id"] = sprint["sprint_id"]`
    # idiom both call sites used. A fresh empty_sprint() carries
    # sprint_id="" and would otherwise be silently dropped here.
    if sprint_id is not None:
        metadata["sprint_id"] = sprint_id
    if is_merge:
        metadata["is_merge"] = True
    if is_free_session:
        metadata["is_free_session"] = True
    # Only the non-default cadence lands (keeps events lean, mirrors the
    # is_free_session/is_merge only-when-true idiom). Absence == commit cadence.
    if review_cadence == "story":
        metadata["review_cadence"] = "story"
    return _common.make_event(
        _common.COMMIT, agent_id, body, files=files, metadata=metadata
    )
