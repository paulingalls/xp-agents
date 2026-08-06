#!/usr/bin/env python3
"""What the schedule gate governs — the exemption predicates for Write/Edit.

Extracted from pre_tool_write.py, which sat at its recorded 463-line ceiling
with no headroom. One responsibility: given a target path and a cwd, decide
whether a write is inside the blast radius of the sprint's schedule gate. The
hook keeps the gate itself (the trigger window, the block, the message); this
module answers only "is this write story code in the working tree".

Every predicate here FAILS CLOSED. An exemption is a claim, and a claim we
cannot substantiate is not one we make: no git root, a git failure, a detached
HEAD, an unreadable MERGE_HEAD — each leaves the gate standing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import branch_names
import identity
import worktree


def _resolves_under(target_file: str, base: Path | str, cwd: str) -> bool:
    """True if `target_file` resolves to a path inside `base`.

    BOTH sides are resolved, and that is the whole point. git reports the
    PHYSICAL toplevel and $SMM_DIR may itself be a symlink, while a target built
    from the hook payload's cwd runs through whatever symlinks the caller had (on
    macOS /tmp is /private/tmp, and mkdtemp hands back /var/folders ->
    /private/var/folders). Resolve one side only and every contained path reads
    as outside — for the schedule gate that means failing OPEN for exactly the
    case it exists to catch.

    Shared by both exemption predicates below. Sharing the path MATH is not
    unioning the exemptions: they stay two predicates with two justifications
    (see the gate in pre_tool_write.run) and only agree on what "inside a
    directory" means.
    """
    p = Path(target_file)
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        p.resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def is_smm_write(smm_dir: Path | None, target_file: str | None, cwd: str) -> bool:
    """True if the write targets a file inside the SMM dir.

    SMM mutations are infrastructure, not implementation, so they are exempt
    from the schedule gate — and, because sprint.json lives there, an SMM write
    is also the repair path when the sprint is unreadable.
    """
    if not smm_dir or not target_file:
        return False
    return _resolves_under(target_file, smm_dir, cwd)


def _is_outside_tree(target_file: str | None, root: str, cwd: str) -> bool:
    """True if the write targets a path outside the git working tree.

    No target is not evidence of being outside, so the gate stands.
    """
    if not target_file:
        return False
    return not _resolves_under(target_file, root, cwd)


def is_out_of_story_scope(target_file: str | None, cwd: str) -> bool:
    """True if the write is outside what the schedule gate governs.

    The gate's claim is "do not write story code before the story is promoted",
    and three kinds of write are not that: one that lands OUTSIDE the working
    tree (a memory file under ~/.claude is not this sprint's implementation — and
    the only way to satisfy the gate for it was to promote a story against a
    customer pause); one made on a FREE branch, where the sprint is not the frame
    at all and /xp-free-close is the right path; and one made while a MERGE is in
    progress, where the file being written is a conflict being resolved, not new
    implementation.

    Free-branch detection keys on branch SHAPE, never on a marker: a marker can be
    `rm`'d to bypass the gate, a branch name cannot be forged without being on it.
    The merge leg is structural for the same reason and a stronger one — an opt-in
    marker can be left behind and would silently disarm the gate for the rest of
    the session, while git creates MERGE_HEAD when the merge starts and removes it
    when the merge ends, so the exemption cannot outlive its reason. The recorded
    misfire: a back-merge onto a sprint branch with stories scheduled and none in
    motion, where resolving the conflicts meant writing to the conflicted files
    and every such write was refused. The commit gate already carries an escape
    for this case.

    Fails closed at every leg. No git root (not a repo, git broken) -> we cannot
    prove the write is out of scope, so we do not exempt it. `merge_in_progress`
    reads "" from a failed `rev-parse` and answers False, so a broken git is not
    a merge. `get_current_branch` returns "" on git failure and the literal
    "HEAD" when detached; neither is a free branch, so both leave the gate
    standing.

    ORDER IS COST, and the branch leg stays LAST. The out-of-tree leg is
    deliberately FIRST: it is pure path math, while the other two each shell out,
    so a write that is already out of tree pays no subprocess at all.
    TestScheduleGateBranchProbeCost and TestScheduleGateMergeProbeCost each pin
    their own leg, so neither can be reordered without a named failure.

    Sibling to `is_smm_write`, and deliberately NOT merged with it — see the
    two-predicate note on the gate in pre_tool_write.run.
    """
    root = worktree.resolve_git_root(cwd)  # memoized per cwd
    if not root:
        # `not root`, not `is None`: an EMPTY root would resolve to the hook
        # process's own cwd (`Path("").resolve()`), against which nearly every
        # target reads as out-of-tree — i.e. exempt. That is fail-OPEN from a
        # falsy value the type says cannot happen. worktree.worktree_path already
        # spells the guard this way; make the invariant total, not probable.
        return False
    if _is_outside_tree(target_file, root, cwd):
        return True
    if identity.merge_in_progress(cwd):
        return True
    return branch_names.is_free_branch(identity.get_current_branch(cwd))
