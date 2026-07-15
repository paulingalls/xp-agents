#!/usr/bin/env python3
"""The mark-done gate: refuse `done` for a story whose merge never landed.

Last session a story was marked `done` while it was NOT merged. `close_common`'s
merge hit a transient `.git/index.lock`; the close pipeline carried on.

The failure was never silent at the GIT level -- `branch_lifecycle._merge_into_target`
sys.exit(1)s on a failed merge with git's stderr attached, and `cmd_merge` returns
non-zero. The silence is that the CALLER is an LLM following skill prose: the close
skill merges, then marks the story done, and nothing deterministic stands between
those two steps. A louder error cannot fix that. Only a gate can.

PROOF COMES FROM GIT, NOT FROM A TOKEN. Recording a `merged_sha` on the story at
merge time was the obvious design and it is a trap: merge succeeds, the state write
then fails, the gate demands the sha, and re-running the merge answers "Already up
to date" -- so no sha can ever be produced and the story is PERMANENTLY un-markable.
A gate whose only repair path is blocked by itself is worse than the bug.

Git already holds the proof, in a form that survives cleanup: no delete path deletes
an unmerged branch. `delete_branch` proves `is_merged_into` ITSELF before it deletes,
and falls back to `-D` only once `survives_delete_of` also holds. So BRANCH ABSENCE
IS PROOF OF MERGE -- which inverts the deleted branch from the thing that would break
a naive ancestor check into the thing that passes it.

That proof is OURS, not git's, and the difference is load-bearing. `git branch -d` is
NOT the safety net it is taken for: its rule is "fully merged in its UPSTREAM branch,
or in HEAD if no upstream was set", and upstream wins when one exists. Story-close
Step 2 pushes with `git push -u`, so on any repo with a remote a plain `-d` deletes a
branch that was merely PUSHED and never merged -- exit 0, warning nobody reads. Left
to git, the keystone would be false on every remote-backed project. `delete_branch`
checks the ancestry up front for exactly this reason; do not "simplify" that away.

Marker-FREE and state-derived, so it stays out of `lead_gates._LEAD_GATES` (which is
the Write/Edit hook's table anyway); see the doctrine note in `pre_tool_write.run`.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branch_resolution
import branching
import event_schema
import sprint_store

# The action stamp on the force-drop record `spawn_teammate` writes when a
# re-spawn `-D`s a genuinely-unmerged branch. Read here to tell a force-dropped
# (ABANDONED) absent branch apart from a merged-then-deleted (SHIPPED) one. The
# literal lives in event_metadata so the producer (spawn_teammate) and this
# consumer share ONE source -- a drifted tag would silently fail the gate open.
_FORCE_DROP_ACTION = event_schema.DEBT_ACTION_BRANCH_FORCE_DROPPED


def _live_force_drop(smm_dir: Path, branch: str, story_id: str) -> dict | None:
    """The latest UNRESOLVED force-drop record naming `branch`, or None.

    `spawn_teammate` writes a `debt` event (metadata.action == branch_force_dropped)
    when a re-spawn force-drops an unmerged branch, and a `status` event carrying
    metadata.resolves clears it once the branch is re-created. This reads the pair
    back: the latest matching debt whose id is NOT in resolved_debt_ids.

    Matching is exact on `metadata.branch == branch` (a drop of a DIFFERENT branch
    must not match) and, when the record names a story, on story_id (a record with
    no story_id matches any).

    Degrades QUIET on an unreadable event log. This check is ADDITIVE over the
    keystone, and branch-absent is the NORMAL close path, so bricking every honest
    close on a corrupt log would be worse than missing this defensive signal. The
    sprint/base/git reads in `merged_block` STAY fail-closed; only this
    annotation-only read degrades quiet.
    """
    try:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    except Exception:
        return None
    resolved = resolutions.get("resolved_debt_ids", set())
    latest: dict | None = None
    for event in events:
        if event.get("type") != _common.DEBT:
            continue
        metadata = event.get("metadata") or {}
        if metadata.get("action") != _FORCE_DROP_ACTION:
            continue
        if metadata.get("branch") != branch:
            continue
        recorded_story = metadata.get("story_id") or ""
        if recorded_story and recorded_story != story_id:
            continue
        if event.get("id") in resolved:
            continue
        latest = event
    return latest


# The one crack in "absence implies merged": spawn_teammate's re-spawn cleanup is
# the sole `remove_worktree(force_branch=True)`. That path now proves the merge first
# (via branch_lifecycle.delete_branch) and only force-drops (`-D`) a branch that is
# genuinely unmerged. The crack is that residual force-drop. It is narrow (a re-spawn
# moves the story back to in-progress, so it is not then marked done) and recorded as
# debt rather than papered over here.


# ---------------------------------------------------------------------------
# What COUNTS as marking a story done -- the command side of the gate
# ---------------------------------------------------------------------------

# The escape hatch. Read off the COMMAND rather than the story, because the gate must
# honour an override before it does any work. The CLI is what enforces that the reason
# is non-empty and writes the debt event -- a hook that merely sees the flag cannot
# police what follows it.
_FORCE_UNMERGED_RE = re.compile(r"--force-unmerged\b")

# Mark-done as an INVOCATION, not as prose: `sprint_cli` must precede the subcommand.
#
# Requiring it is not belt-and-braces. Without it the pattern matches text that merely
# DESCRIBES the command, and the gate fires on a `git commit` whose MESSAGE happens to
# mention `update-story <id> done` -- which blocked the very commit that added this
# gate, because the message documented the flag. A gate that refuses a commit over what
# its message SAYS is how people learn to route around gates.
#
# `(?:\\\n|[^\n])*?` spans a backslash-continuation because the shipped invocation is
# wrapped (`sprint_cli.py --smm-dir X \` newline `update-story story-NNN done`). A
# plain `[^\n]*?` matches every hand-written single-line test and NONE of /xp-accept
# Step 4 -- dead precisely where it is needed. Spanning the continuation but NOT a bare
# newline is also what keeps the prose false-positive shut: a heredoc message is
# separated from the CLI's name by real newlines, not by `\`-continuations.
_MARK_DONE_RE = re.compile(
    r"sprint_cli(?:\.py)?\b(?:\\\n|[^\n])*?\bupdate-story\s+(\S+)\s+done\b"
)

# The OTHER writer of `done` -- a compare-and-swap onto the same field. The gate did
# not know this subcommand existed, so the whole merge proof was one flag away. It
# cannot match _MARK_DONE_RE (there `update-story` is followed by whitespace, here by
# `-if`), so the two patterns are disjoint by construction.
_MARK_DONE_IF_RE = re.compile(
    r"sprint_cli(?:\.py)?\b(?:\\\n|[^\n])*?\bupdate-story-if\s+(\S+)"
    r"(?:\\\n|[^\n])*?--new(?:=|\s+)done\b"
)

# The shell strips these before the CLI ever sees the id, so we must too: `\S+` used to
# capture `'story-001'` WITH its quotes, `get_story` found no such story, and the
# ValueError arm below read that as "nothing to check" and ALLOWED the mark-done.
# Quoting an id is ordinary -- /xp-schedule quotes `"$FIRST"` in the same pipeline.
_SHELL_QUOTES = "\"'"

# One Bash call can hold several invocations; each is judged on its OWN text. An
# override belongs to the invocation that TYPED it, and a `--force-unmerged` matched
# against the whole command would waive a chained second story that never carried one.
# `(?<!\\)\n` leaves the wrapped-invocation shape above intact while still splitting
# genuine newlines.
_SEGMENT_RE = re.compile(r"&&|\|\||;|(?<!\\)\n")


def mark_done_invocations(command: str) -> list[tuple[str, bool]]:
    """Every `(story_id, force_overridden)` `command` marks `done`, in first-seen order.

    EVERY one. The gate used to read the FIRST match only, and a close that wraps up
    two stories in one chained command (`... done && ... done`) is the shape that makes
    the second one interesting. A gate that inspects one of two writes is not a gate.

    A story id hidden in a shell variable (`update-story "$SID" done`) still yields
    nothing -- the hook sees the literal text, never its value. That failure does LESS
    (no gate) rather than blocking honest work, and it is closed for good only at the
    engine altitude, where every writer of the field converges. Recorded as debt.
    """
    found: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for segment in _SEGMENT_RE.split(command):
        forced = bool(_FORCE_UNMERGED_RE.search(segment))
        for regex in (_MARK_DONE_RE, _MARK_DONE_IF_RE):
            for match in regex.finditer(segment):
                story_id = match.group(1).strip(_SHELL_QUOTES)
                if story_id and story_id not in seen:
                    seen.add(story_id)
                    found.append((story_id, forced))
    return found


def merged_block(smm_dir: Path, cwd: str, story_id: str) -> str | None:
    """Reason to refuse `update-story <id> done`, or None to allow.

    Fails CLOSED on a bad read: a corrupt sprint.json or a base branch that cannot
    be honestly resolved blocks, rather than waving the mark-done through with the
    gate blind. Fails OPEN on "there is nothing to check" -- no sprint, no such
    story -- which is the same contract `close_verify_gate.verify_gate_block` keeps,
    and what lets a project with no sprint at all use the CLI.
    """
    try:
        story = sprint_store.get_story(smm_dir, story_id)
    except sprint_store.SprintCorruptError as exc:
        # MUST precede the ValueError arm: SprintCorruptError SUBCLASSES ValueError,
        # so catching the parent first would read a corrupt sprint as "no sprint"
        # and pass -- fail-OPEN on exactly the unreadable state that must fail shut.
        return (
            f"sprint.json cannot be read ({exc}). Whether the story's merge landed "
            "is unknowable, so it is not marked done. Repair the sprint and retry."
        )
    except (ValueError, OSError):
        return None  # no sprint / no such story -- nothing to verify

    if story.get("status") == "done":
        return None  # idempotent re-mark

    branch = story.get("branch_name")
    if not branch:
        return None  # never branched (stage 0/1) -- no merge to prove

    if not branch_resolution.ref_exists(cwd, "HEAD"):
        # The keystone's PASS arm is reached by a failed git read, not only by a
        # deleted branch: `branch_exists` shells out and answers False on ANY
        # non-zero exit -- branch gone, cwd not a repo, git broken. Absence only
        # proves a merge if git could actually be asked. Prove git answers here
        # first, so a bad read fails CLOSED like every other read in this gate.
        return (
            f"git cannot be read in {cwd}, so whether {branch} merged is "
            "unknowable. Re-run from the repository root."
        )

    if not branch_resolution.branch_exists(cwd, branch):
        # THE KEYSTONE. `delete_branch` refuses to delete a branch it has not proved
        # merged (it does NOT delegate that to `git branch -d`, which deletes a
        # merely-pushed branch), so absence IS the proof. This is also the normal
        # close path: the merge deletes the story branch, mark-done runs afterwards.
        #
        # The ONE exception: `spawn_teammate`'s re-spawn cleanup force-drops a
        # genuinely-unmerged branch (`-D`), leaving it absent WITHOUT a merge. That
        # path records a force-drop; consult it here. A live (unsuperseded) drop of
        # THIS branch means the absence is abandonment, not a merge -> BLOCK. A
        # merged-then-deleted branch has no such record, so it still ALLOWS.
        if _live_force_drop(smm_dir, branch, story_id) is not None:
            return (
                f"{branch} was force-dropped while unmerged during a re-spawn and "
                f"never re-created or merged -- the work was abandoned, not shipped. "
                f"Marking this story done would record work that did not land. If it "
                f"truly is complete, say so on the record: "
                f'update-story {story_id} done --force-unmerged "<reason>".'
            )
        return None

    # The branch is still here, so it must be an ancestor of the base it merges into.
    try:
        base = branch_resolution.get_story_base_branch_required(smm_dir, cwd)
    except (ValueError, OSError) as exc:
        # The `_required` sibling raises rather than degrading to the primary branch:
        # a silent primary would check a sprint-branch story against `main` and block
        # every honest close. Unresolvable base = dishonest state = fail closed.
        return (
            f"the story's base branch cannot be resolved ({exc}), so whether "
            f"{branch} merged is unknowable. Repair sprint.json and retry."
        )

    if branching.is_merged_into(cwd, branch, base):
        return None  # merged, but the branch survived (a worktree still holds it)

    return (
        f"{branch} is NOT merged into {base} -- the merge never landed, so marking "
        f"this story done would record work that did not ship. Re-run the close "
        f"(the merge is retryable; the branch is intact). If the merge truly is "
        f"unnecessary, say so on the record: "
        f'update-story {story_id} done --force-unmerged "<reason>".'
    )
