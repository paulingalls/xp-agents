#!/usr/bin/env python3
"""CLI dispatch for branch lifecycle operations.

Thin CLI layer over branching.py library functions. All callers
invoke `python3 branching.py <subcommand>` — branching.py's
__main__ guard delegates here.
"""

import argparse
import json
import sys
from pathlib import Path

import acceptance_env
import branch_queries
import branching
import identity
import worktree


def _print_or_skip(result: str | None, min_stage: int, *, resumed: bool = False) -> int:
    if result:
        prefix = "resumed" if resumed else "created"
        print(f"{prefix}: {result}")
    else:
        print(f"Skipped (stage < {min_stage})")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.branch_name(user_ns, args.story, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_story_branch(
        args.cwd, args.story, args.slug, Path(args.smm_dir), base=args.base
    )
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["story"], resumed=existed)


def _resolve_target(args: argparse.Namespace) -> str:
    return args.target or branching.get_merge_target(Path(args.smm_dir), args.cwd)


def _cmd_delete(args: argparse.Namespace) -> int:
    ok = branching.delete_branch(args.cwd, args.branch)
    return 0 if ok else 1


def _cmd_create_sprint(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.sprint_branch_name(user_ns, args.sprint, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_sprint_branch(args.cwd, args.sprint, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["sprint"], resumed=existed)


def _cmd_get_base(args: argparse.Namespace) -> int:
    result = branching.get_story_base_branch(Path(args.smm_dir), args.cwd)
    print(result)
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    stage = branching.get_branching_stage(Path(args.smm_dir))
    print(stage)
    return 0


def _cmd_get_primary(args: argparse.Namespace) -> int:
    print(branching.get_primary_branch(Path(args.smm_dir)))
    return 0


def _cmd_get_target(args: argparse.Namespace) -> int:
    print(branching.get_merge_target(Path(args.smm_dir), args.cwd))
    return 0


def _cmd_extract_story_id(args: argparse.Namespace) -> int:
    """Print story-NNN from `<user>/story-NNN-<slug>`. Empty if no match.

    Always exits 0 — empty stdout signals "not a story branch" cleanly
    so SKILL.md callers can `[ -n "$STORY_ID" ]` gate without needing
    to distinguish error vs no-match exit codes.
    """
    print(identity.extract_story_id(args.branch) or "")
    return 0


def _cmd_list_teammate_worktree_paths(args: argparse.Namespace) -> int:
    """Print ``story-id\\tabs-path`` per live teammate. Empty stdout = none.

    Tab-delimited: worktree paths can contain spaces on macOS
    (``/Users/foo bar/...``); tab guarantees consumers can split on a
    single byte that cannot legally appear in either field.
    """
    for story_id, wt_path in worktree.list_live_teammate_worktree_paths(args.cwd):
        print(f"{story_id}\t{wt_path}")
    return 0


def _cmd_find_teammate_worktree(args: argparse.Namespace) -> int:
    """Print teammate worktree NAME for a story id, empty if none live.

    Always exits 0 — empty stdout signals "no live teammate worktree"
    (solo mode, or already cleaned up) so SKILL.md callers can gate on
    non-empty without distinguishing error vs no-match.
    """
    print(worktree.find_teammate_worktree_for_story(args.story_id, args.cwd) or "")
    return 0


def _cmd_find_closing_teammate_worktree(args: argparse.Namespace) -> int:
    """Print ``<abs-path>\\t<branch>`` for the worktree of the in-reviewing story.

    Implicit-derivation discovery for /xp-story-close: pairs the live
    teammate worktree with its sprint.json story status; prints exactly
    when one worktree's story is `reviewing`. Under close-then-done
    semantics, /xp-story-close runs while the story is still in
    `reviewing` (mark-done is the FINAL step after merge). Empty stdout
    = no match (solo, or no teammate finished). Non-zero exit + stderr
    on multi-match — that signals broken /xp-accept iteration; fail loud
    rather than guess which worktree to close.

    Tab-delimited: worktree paths can contain spaces on macOS; the
    prior space-delimited emit forced bash consumers to lean on the
    implicit "git refs cannot contain spaces" invariant via
    ``${var% *}``/``${var##* }``. That invariant happens to hold but is
    not self-documenting — tab makes the contract explicit.
    """
    try:
        result = worktree.find_closing_teammate_worktree(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if result is not None:
        abs_path, branch = result
        print(f"{abs_path}\t{branch}")
    return 0


def _cmd_merge_branch(args: argparse.Namespace) -> int:
    branching.merge_branch(args.cwd, args.branch, _resolve_target(args))
    return 0


def _cmd_create_plan(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.plan_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_plan_branch(args.cwd, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["plan"], resumed=existed)


def _cmd_create_free(args: argparse.Namespace) -> int:
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.free_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_free_branch(
        args.cwd, args.slug, Path(args.smm_dir), base=args.base
    )
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["free"], resumed=existed)


def _cmd_list_free(args: argparse.Namespace) -> int:
    for b in branching.list_free_branches(args.cwd):
        print(b)
    return 0


def _cmd_list_story_orphans(args: argparse.Namespace) -> int:
    """Print story branches not backed by an active sprint story.

    Active = any non-terminal status (see
    ``sprint_schema.ACTIVE_STORY_STATUSES``); the closing/reviewing
    branches stay alive for /xp-story-close merge and /xp-accept
    verification respectively and are NOT orphan.
    """
    for b in branch_queries.list_orphan_story_branches(args.cwd, Path(args.smm_dir)):
        print(b)
    return 0


def _cmd_check_divergence(args: argparse.Namespace) -> int:
    result = branching.check_plan_divergence(
        args.cwd, Path(args.smm_dir), args.threshold
    )
    if result is None:
        print("No plan branch found")
        return 0
    print(json.dumps(result))
    return 0


def _cmd_accept_env_prepare(args: argparse.Namespace) -> int:
    """Detach the main checkout onto a teammate story's tip; print the restore ref.

    The SKILL captures stdout (the sprint base) to pass back to
    ``accept-env restore`` after the acceptance harness runs.
    """
    try:
        tip, base = acceptance_env.resolve_story_tip(
            Path(args.smm_dir), args.cwd, args.story
        )
        acceptance_env.checkout_story_tip(args.cwd, tip)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    print(base)
    return 0


def _cmd_accept_env_restore(args: argparse.Namespace) -> int:
    """Return the main checkout to ``--restore-ref`` (the base from prepare)."""
    try:
        acceptance_env.restore(args.cwd, args.restore_ref)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def _cmd_accept_env_recover(args: argparse.Namespace) -> int:
    """Heal an interrupted main checkout; print the recovered state (else nothing)."""
    try:
        state = acceptance_env.recover(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if state:
        print(state)
    return 0


def _cmd_accept_env_inspect(args: argparse.Namespace) -> int:
    """Print a read-only prepare-readiness snapshot for the /xp-accept preload.

    One TSV row per live teammate worktree:
    ``story_id<TAB>path<TAB>tip<TAB>restore_ref``. A trailing
    ``MAIN_STATE<TAB><state>`` line flags a window needing recovery before a
    detached-HEAD checkout (interrupted state, else dirty); omitted on a clean
    tree. Tab-delimited because macOS paths can contain spaces.
    """
    try:
        snap = acceptance_env.inspect(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    for story_id, path, tip, restore_ref in snap["rows"]:
        print(f"{story_id}\t{path}\t{tip}\t{restore_ref}")
    if snap["main_state"]:
        print(f"MAIN_STATE\t{snap['main_state']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Branch lifecycle operations")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a story branch")
    p_create.add_argument("--cwd", required=True)
    p_create.add_argument("--story", required=True)
    p_create.add_argument("--slug", required=True)
    p_create.add_argument("--base", default=None, help="Fork from this ref")
    p_create.set_defaults(func=_cmd_create)

    p_delete = sub.add_parser("delete", help="Delete a branch")
    p_delete.add_argument("--cwd", required=True)
    p_delete.add_argument("--branch", required=True)
    p_delete.set_defaults(func=_cmd_delete)

    p_csprint = sub.add_parser("create-sprint", help="Create a sprint branch")
    p_csprint.add_argument("--cwd", required=True)
    p_csprint.add_argument("--sprint", required=True)
    p_csprint.add_argument("--slug", required=True)
    p_csprint.set_defaults(func=_cmd_create_sprint)

    p_base = sub.add_parser("get-base", help="Print story base branch")
    p_base.add_argument("--cwd", required=True)
    p_base.set_defaults(func=_cmd_get_base)

    p_stage = sub.add_parser("stage", help="Print branching stage")
    p_stage.set_defaults(func=_cmd_stage)

    p_get_primary = sub.add_parser(
        "get-primary", help="Print primary integration branch"
    )
    p_get_primary.set_defaults(func=_cmd_get_primary)

    p_get_target = sub.add_parser("get-target", help="Print merge target")
    p_get_target.add_argument("--cwd", required=True)
    p_get_target.set_defaults(func=_cmd_get_target)

    p_merge_branch = sub.add_parser(
        "merge-branch", help="Merge any branch (sprint or plan) into a target"
    )
    p_merge_branch.add_argument("--cwd", required=True)
    p_merge_branch.add_argument("--branch", required=True)
    p_merge_branch.add_argument("--target", default=None)
    p_merge_branch.set_defaults(func=_cmd_merge_branch)

    p_create_plan = sub.add_parser("create-plan", help="Create or resume a plan branch")
    p_create_plan.add_argument("--cwd", required=True)
    p_create_plan.add_argument("--slug", required=True)
    p_create_plan.set_defaults(func=_cmd_create_plan)

    p_create_free = sub.add_parser("create-free", help="Create or resume a free branch")
    p_create_free.add_argument("--cwd", required=True)
    p_create_free.add_argument("--slug", required=True)
    p_create_free.add_argument("--base", default=None, help="Fork from this ref")
    p_create_free.set_defaults(func=_cmd_create_free)

    p_list_free = sub.add_parser("list-free", help="List the user's free branches")
    p_list_free.add_argument("--cwd", required=True)
    p_list_free.set_defaults(func=_cmd_list_free)

    p_list_orphans = sub.add_parser(
        "list-story-orphans", help="List orphan story branches"
    )
    p_list_orphans.add_argument("--cwd", required=True)
    p_list_orphans.set_defaults(func=_cmd_list_story_orphans)

    p_xsid = sub.add_parser(
        "extract-story-id",
        help="Print story-NNN from a `<user>/story-NNN[-<slug>]` branch",
    )
    p_xsid.add_argument("--branch", required=True)
    p_xsid.set_defaults(func=_cmd_extract_story_id)

    p_ltwp = sub.add_parser(
        "list-teammate-worktree-paths",
        help="List live teammate worktrees as `story-id<TAB>abs-path` rows",
    )
    p_ltwp.add_argument("--cwd", required=True)
    p_ltwp.set_defaults(func=_cmd_list_teammate_worktree_paths)

    p_ftw = sub.add_parser(
        "find-teammate-worktree",
        help="Print live teammate worktree name for a story id (empty if none)",
    )
    p_ftw.add_argument("--story-id", required=True)
    p_ftw.add_argument("--cwd", required=True)
    p_ftw.set_defaults(func=_cmd_find_teammate_worktree)

    p_fctw = sub.add_parser(
        "find-closing-teammate-worktree",
        help=(
            "Print `<abs-path><TAB><branch>` for the worktree of the in-reviewing story"
        ),
    )
    p_fctw.add_argument("--cwd", required=True)
    p_fctw.set_defaults(func=_cmd_find_closing_teammate_worktree)

    p_div = sub.add_parser("check-divergence", help="Check plan branch divergence")
    p_div.add_argument("--cwd", required=True)
    p_div.add_argument("--threshold", type=int, default=10)
    p_div.set_defaults(func=_cmd_check_divergence)

    p_ae = sub.add_parser(
        "accept-env",
        help="Serial main-checkout acceptance env (prepare/restore/recover)",
    )
    ae = p_ae.add_subparsers(dest="accept_env_action", required=True)
    ae_prep = ae.add_parser(
        "prepare", help="Detach onto a story's tip; print the restore ref"
    )
    ae_prep.add_argument("--cwd", required=True)
    ae_prep.add_argument("--story", required=True)
    ae_prep.set_defaults(func=_cmd_accept_env_prepare)
    ae_rest = ae.add_parser("restore", help="Restore the main checkout to a ref")
    ae_rest.add_argument("--cwd", required=True)
    ae_rest.add_argument("--restore-ref", required=True)
    ae_rest.set_defaults(func=_cmd_accept_env_restore)
    ae_rec = ae.add_parser("recover", help="Heal an interrupted main checkout")
    ae_rec.add_argument("--cwd", required=True)
    ae_rec.set_defaults(func=_cmd_accept_env_recover)
    ae_insp = ae.add_parser(
        "inspect", help="Read-only prepare-readiness snapshot (rows + MAIN_STATE flag)"
    )
    ae_insp.add_argument("--cwd", required=True)
    ae_insp.set_defaults(func=_cmd_accept_env_inspect)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
