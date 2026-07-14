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

Git already holds the proof, in a form that survives cleanup: every delete path
refuses to delete an unmerged branch. `delete_branch` tries `git branch -d` (git
itself refuses when unmerged) and falls back to `-D` ONLY when `survives_delete_of`
AND `is_merged_into` have already proved the merge. So BRANCH ABSENCE IS
GIT-ENFORCED PROOF OF MERGE -- which inverts the deleted branch from the thing that
would break a naive ancestor check into the thing that passes it.

Marker-FREE and state-derived, so it stays out of `lead_gates._LEAD_GATES` (which is
the Write/Edit hook's table anyway); see the doctrine note in `pre_tool_write.run`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branch_resolution
import branching
import sprint_store

# The one crack in "absence implies merged": spawn_teammate's re-spawn cleanup is
# the sole `remove_worktree(force_branch=True)` -- a `-D` with no merge proof. It is
# narrow (a re-spawn moves the story back to in-progress, so it is not then marked
# done) and recorded as debt rather than papered over here.


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

    if not branch_resolution.branch_exists(cwd, branch):
        # THE KEYSTONE. Git refused to delete this branch unless it was merged, so
        # its absence IS the proof. This is also the normal close path: the merge
        # deletes the story branch, and mark-done runs afterwards.
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
