#!/usr/bin/env python3
"""The `delete` and `merge-branch` subcommands, and the one question they share.

Split out of branching_cli.py when adding the story-base arm pushed that file
past the 500-line cap. These five functions are one unit: both subcommands ask
`_resolve_target` "which branch does --branch belong to?", and both answers are
only as honest as `_is_current_sprint_story_branch` and `_delete_refusal` make
them. branching_cli re-exports them by identity, so `branching_cli.<name>` still
resolves for callers and tests that reach for it there.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import branching
import identity
import sprint_store
import worktree


def _is_current_sprint_story_branch(smm_dir: Path, branch: str) -> bool:
    """True when ``branch`` is the branch RECORDED for a story of THIS sprint.

    Deliberately narrower than "the name looks like a story branch": kickoff's
    orphan listing surfaces every story branch with no ACTIVE story behind it,
    so it mixes this sprint's finished stories with PRIOR sprints' leftovers,
    and only the former are based on the sprint branch sprint.json names.
    Matching the recorded ``branch_name`` is what holds that line — story ids
    restart at story-001 every sprint, so a prior sprint's orphan collides with
    a live story id as a matter of course. The id stays as the cheap first gate:
    a free or plan branch has none, never reads the sprint, resolves as before.

    Reads through the LOUD ``load_sprint`` — a corrupt sprint.json must not
    quietly become "not a story branch", hence "prove it against primary".
    """
    if identity.extract_story_id(branch) is None:
        return False
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return False
    return any(s.get("branch_name") == branch for s in sprint["stories"])


def _resolve_target(
    args: argparse.Namespace, story_base: Callable[[Path, str], str]
) -> str:
    """The ONE branch ``--branch`` is proven against, or merged into.

    Three arms, most-specific first: an explicit ``--target`` always wins; a
    branch this sprint owns resolves to its STORY BASE; anything else keeps
    ``get_merge_target`` (plan branch or primary), unchanged. One target, never
    a candidate list: retrying a refusal against a second ref would widen the
    set of branches delete can prove, which is not what this question asks.
    ``story_base`` is a parameter because the two callers must NOT share one —
    each says why at its own definition.

    Raises ValueError on a corrupt sprint.json (and on an unresolvable base when
    handed the ``_required`` resolver). BOTH callers catch it: this is the only
    place either of them reads the SMM, and neither may traceback at a user who
    typed a documented command.
    """
    if args.target:
        return args.target
    smm_dir = Path(args.smm_dir)
    if _is_current_sprint_story_branch(smm_dir, args.branch):
        return story_base(smm_dir, args.cwd)
    return branching.get_merge_target(smm_dir, args.cwd)


def _delete_refusal(cwd: str, branch: str, target: str) -> str:
    """Why the delete was refused — reporting only what we actually CHECKED.

    Every arm re-derives its fact from git rather than asserting one. A single
    hardcoded "it is not merged into <target>" is a LIE in three reachable
    states: the branch does not exist, the target does not resolve (so no
    ancestry was proven either way), and the target resolved to the branch
    itself. Sending a user to `git merge` over a branch that was never there is
    worse than the silence it replaced — silence at least misleads no one.

    A branch checked out in a worktree cannot be deleted no matter how merged it
    is, and that is a different fix (free the worktree) from an unmerged branch
    (merge it). Do NOT borrow close_common's escape hatch of returning 0 there:
    that leans on close-specific knowledge — cleanup_teammate will remove the
    branch later — which kickoff does not have.
    """
    if not branching.branch_exists(cwd, branch):
        return f"there is no local branch '{branch}'."
    if worktree.branch_held_by_worktree(cwd, branch):
        return (
            f"'{branch}' is checked out in a worktree — a checked-out branch "
            f"cannot be deleted. Switch that worktree to another branch (or "
            f"remove the worktree), then delete."
        )
    if not branching.survives_delete_of(cwd, branch, target):
        return (
            f"cannot prove '{branch}' is safe to delete: its merge target "
            f"resolved to '{target}', which is not a ref that would survive the "
            f"delete (it is the branch itself, or not a ref at all). Pass "
            f"--target <the branch it was merged into>."
        )
    if not branching.is_merged_into(cwd, branch, target):
        return (
            f"refusing to delete '{branch}': it is not merged into '{target}' "
            f"(it has commits '{target}' does not). Merge it first, or delete it "
            f"by hand if the work is meant to be discarded."
        )
    return f"git refused to delete '{branch}'. Run `git branch -d {branch}` to see why."


def _cmd_delete(args: argparse.Namespace) -> int:
    """Delete a branch, telling delete_branch what it was merged INTO.

    Without a merge_target, delete_branch's ancestry-proven ``-D`` fallback can
    never engage — so from the CLI it was unreachable, and `git branch -d`
    refuses whenever a branch's tip differs from its upstream tracking ref even
    though it is merged: the case worktree teammates hit at every close.
    xp-kickoff says "merge ... then delete", and did exactly that — merged, then
    called delete without saying what the target was. The user answered "merge",
    got the merge, and then a silent exit 1.

    Defaulting the target is safe because ``delete_branch`` owns BOTH halves of
    the ``-D`` proof (ancestry AND a surviving ref — read it there, it is not
    re-derived here). The ancestry half is also exactly kickoff's own rule ("do
    not auto-delete branches with commits ahead"), now enforced by construction
    rather than by remembering. The default comes from ``_resolve_target``, which
    kickoff's merge-branch also asks, so the two legs pick the same branch for
    the same input — but it can answer with the recorded PLAN branch, which is
    why the surviving-ref half exists.

    The one place they part is the resolver passed in: DEGRADING here, because
    proving against a base that fell back to primary costs at worst a refusal
    the caller can override with ``--target``, where merging into one would put
    story work on the release branch.

    On refusal: exit 1 WITH a reason we verified. The silence was half the bug;
    a confidently wrong reason would be the other half back again. A corrupt
    sprint.json refuses too — the membership read is deliberately loud — but it
    still has to READ as a refusal, so catch it here rather than let a traceback
    take the place of the sentence the user has to act on.
    """
    try:
        target = _resolve_target(args, branching.get_story_base_branch)
    except ValueError as exc:
        sys.stderr.write(f"delete: {exc}\n")
        return 1
    if branching.delete_branch(args.cwd, args.branch, merge_target=target):
        return 0
    sys.stderr.write(f"delete: {_delete_refusal(args.cwd, args.branch, target)}\n")
    return 1


def _cmd_merge_branch(args: argparse.Namespace) -> int:
    """Merge a branch into the target it belongs to.

    Takes the ``_required`` resolver — the opposite posture from ``_cmd_delete``
    — because this WRITES a merge commit into whatever it is handed and proves
    nothing first. Its ValueError names both candidate branches and the way out,
    so print it like ``create`` does rather than bury it under a traceback.
    """
    try:
        target = _resolve_target(args, branching.get_story_base_branch_required)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    branching.merge_branch(args.cwd, args.branch, target)
    return 0
