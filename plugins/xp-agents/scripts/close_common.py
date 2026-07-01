#!/usr/bin/env python3
"""Shared close-skill pipeline.

Each XP close skill (sprint, plan, free, story) duplicated the same
shell idioms for pre-flight checks, branch push, PR creation, and
chained merge+push+delete. This module collapses those into one
script with four subcommands the SKILL.md files invoke instead of
inlining the bash:

    close_common.py preflight --cwd PATH --current B --target B
    close_common.py push      --cwd PATH --branch B
    close_common.py create-pr --cwd PATH --base B --head B \\
                              --title T --body B
    close_common.py merge     --cwd PATH --source B --target B

Detection (no remote, no gh) is internal — callers pass branch names
and let the script decide whether to skip. Orchestrator-only steps
(Agent fork, AskUserQuestion, mode-specific tail) stay in SKILL.md.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve sibling branching module without modifying caller sys.path.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import acceptance_env
import branching
import close_verify_gate
import commits
import git_hooks
import git_remote
import identity
import sprint_store
import trailer_gate
import worktree
from merge_commit_event import append_merge_commit_event


def pre_commit_hook_present(repo_root: str) -> bool:
    """Return True when the project runs tests via a git hook on commit/push.

    Strict — defers to ``git_hooks.will_fire_hook`` (markers + executable
    pre-commit/pre-push, honoring ``core.hooksPath``). Non-executable
    scripts and ``.sample`` files don't qualify because git won't fire them.
    """
    return git_hooks.will_fire_hook(repo_root)


def _run_or_relay(argv: list[str], cwd: str, success_msg: str | None = None) -> int:
    """Run argv via subprocess; relay stderr + return code on failure.

    On success, print success_msg if provided. Single source of truth for
    the success/relay-stderr pattern shared by cmd_push and cmd_merge's
    inner push. cmd_create_pr does its own dispatch because it needs the
    raw stdout (PR URL).
    """
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return r.returncode
    if success_msg:
        print(success_msg)
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    if not branching.is_worktree_clean(args.cwd):
        print(
            "preflight failed: worktree must be clean "
            "(commit or stash uncommitted changes)",
            file=sys.stderr,
        )
        return 1
    if args.current == args.target:
        print(
            f"preflight failed: current branch ({args.current}) IS target — "
            "nothing to merge",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    if not git_remote.has_remote(args.cwd):
        print("skipped: no remote configured")
        return 0
    # Solo: the branch is checked out in this checkout — push directly (HEAD is
    # already the story tip, deps present). Teammate: the branch is held by the
    # teammate worktree and this (main) checkout sits on the story base.
    # Pushing from the worktree fires the project's pre-push hook THERE, where a
    # fresh worktree has no installed deps (v3.9.0 design) → ERR_MODULE_NOT_FOUND.
    # Relocate the push to the main checkout instead (see _push_relocated).
    if identity.get_current_branch(args.cwd) == args.branch:
        return _run_or_relay(
            ["git", "push", "-u", "origin", args.branch],
            cwd=args.cwd,
            success_msg=f"pushed: {args.branch}",
        )
    return _push_relocated(args)


def _push_relocated(args: argparse.Namespace) -> int:
    """Push a teammate story branch from the main checkout, not its worktree.

    The branch is held by the teammate worktree (which has the code but no
    installed deps). Detach the main checkout onto the story tip so the
    project's pre-push hook runs with the main checkout's deps against the
    story's code, push, then restore — reusing acceptance_env's Mechanism A.
    The story tip is the branch ref (shared across worktrees); the restore
    target is the story base branch the orchestrator sits on. `restore` runs in
    a `finally` so a red pre-push hook never leaves the main checkout detached.
    """
    if not args.smm_dir:
        sys.stderr.write(
            "push relocate refused: --smm-dir is required to resolve the base "
            "ref for a teammate-worktree branch\n"
        )
        return 1
    smm_dir = Path(args.smm_dir)
    tip = subprocess.run(
        ["git", "rev-parse", args.branch], cwd=args.cwd, capture_output=True, text=True
    )
    if tip.returncode != 0:
        sys.stderr.write(tip.stderr)
        return 1
    tip_sha = tip.stdout.strip()
    restore_ref = branching.get_story_base_branch(smm_dir, args.cwd)
    try:
        acceptance_env.recover(smm_dir, args.cwd)
        acceptance_env.checkout_story_tip(args.cwd, tip_sha)
    except ValueError as exc:
        sys.stderr.write(f"push relocate refused: {exc}\n")
        return 1
    restore_err: ValueError | None = None
    try:
        push_rc = _run_or_relay(
            ["git", "push", "-u", "origin", args.branch],
            cwd=args.cwd,
            success_msg=f"pushed: {args.branch}",
        )
    finally:
        # Restore is mandatory — always attempted even when the push raised or
        # returned non-zero, so a red pre-push hook never leaves main detached.
        # A restore failure is captured (not re-raised here) and surfaced below
        # so it never masks an in-flight push exception (no `return` in finally).
        try:
            acceptance_env.restore(args.cwd, restore_ref)
        except ValueError as exc:
            restore_err = exc
    # A restore failure must never be a bare traceback or a silent rc=0 with
    # main detached: surface it loud + actionable and force non-zero.
    if restore_err is not None:
        sys.stderr.write(
            f"push relocate: {restore_err}\n"
            f"pushed but FAILED to restore the main checkout to "
            f"{restore_ref}; it may be left detached — run "
            f"`git -C {args.cwd} checkout {restore_ref}`\n"
        )
        return 1
    return push_rc


def cmd_create_pr(args: argparse.Namespace) -> int:
    if shutil.which("gh") is None:
        print("skipped: gh not on PATH")
        return 0
    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            args.base,
            "--head",
            args.head,
            "--title",
            args.title,
            "--body",
            args.body,
        ],
        cwd=args.cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    # gh may emit info/warning lines around the URL; pick the last
    # line that looks like a github PR URL so trailing confirmation
    # text doesn't poison the trailing rsplit.
    pr_url = ""
    for raw in reversed(result.stdout.splitlines()):
        line = raw.strip()
        if "/pull/" in line and line.startswith("http"):
            pr_url = line
            break
    if not pr_url:
        sys.stderr.write(
            f"create-pr: could not parse PR URL from gh stdout:\n{result.stdout}"
        )
        return 1
    print(pr_url.rsplit("/", 1)[-1])
    return 0


def cmd_hook_present(args: argparse.Namespace) -> int:
    """Print 'present' or 'absent' for the close-skill preloads."""
    print("present" if pre_commit_hook_present(args.cwd) else "absent")
    return 0


def cmd_diff_command(args: argparse.Namespace) -> int:
    """Print `gh pr diff <N>` for numeric PR_OUTPUT, else `git diff <target>...HEAD`.

    Non-numeric input falls through to git diff so the reviewer never
    sees a malformed gh invocation when create-pr skipped or emitted prose.
    """
    pr_output = args.pr_output.strip()
    if pr_output.isdigit():
        print(f"gh pr diff {pr_output}")
    else:
        print(f"git diff {args.target}...HEAD")
    return 0


def cmd_close_review_gate(args: argparse.Namespace) -> int:
    """Emit CLOSE_CODE_FILE_COUNT and the RUN_FULL_CODE_REVIEW threshold flag.

    The shared Step 4b runs the broad workflow /code-review at sprint/plan/free
    close ONLY when the cumulative close diff (``<target>...HEAD``) has at least
    REVIEW_CYCLE_THRESHOLD code files — per-increment self-find already covered
    smaller diffs. Fails safe to false (count 0) when the range can't resolve.
    """
    count = len(commits.get_code_files_in_range(args.cwd, args.target))
    run_full = count >= commits.REVIEW_CYCLE_THRESHOLD
    print(f"CLOSE_CODE_FILE_COUNT={count}")
    print(f"RUN_FULL_CODE_REVIEW={'true' if run_full else 'false'}")
    return 0


def _review_clean_block(review_cwd: str) -> str:
    """Refusal message when the post-review target worktree is dirty, else "".

    Reviewer fixes applied during the close review (xp-story-close Step 4.5b)
    land in the teammate worktree; if left uncommitted, the merge (whose branch
    tip lacks them) followed by Step 7b worktree removal would silently drop
    them. This is a second clean-check AFTER the review — Step 1 preflight only
    checks BEFORE it. Empty *review_cwd* (solo close, or the arg omitted) skips
    the check; solo working-tree edits persist in the checkout rather than being
    deleted, so only the teammate path needs it.
    """
    if not review_cwd:
        return ""
    if branching.is_worktree_clean(review_cwd):
        return ""
    return (
        f"merge refused: review target {review_cwd} has uncommitted changes "
        "(likely a reviewer fix from the close review). Commit it "
        f"(git -C {review_cwd} commit -am ...) then re-run — the worktree "
        "cleanup would otherwise discard it."
    )


def cmd_merge(args: argparse.Namespace) -> int:
    """Chained merge --no-ff + (push target if remote) + delete source.

    Any step failing aborts the chain — no push or delete on merge
    failure, no delete on push failure. Source branch always survives
    a failed step so the user can resolve and retry.

    A deterministic verify-gate backstop runs FIRST (before merge), so a
    skipped SKILL prose gate can't merge an untouched/red story. See
    close_verify_gate.verify_gate_block.

    branching.merge_branch sys.exit(1)s on conflict (with git's stderr
    already emitted), so we trust it to bail. delete_branch returns
    False on failure (e.g. unmerged commits) — we surface and abort.
    """
    block = close_verify_gate.verify_gate_block(args)
    if block:
        sys.stderr.write(block + "\n")
        return 1

    review_block = _review_clean_block(getattr(args, "review_clean_cwd", "") or "")
    if review_block:
        sys.stderr.write(review_block + "\n")
        return 1

    branching.merge_branch(args.cwd, args.source, target=args.target)
    print(f"merged: {args.source} -> {args.target}")

    # Emit a commit event for the merge HEAD; closes the merge-gap hole
    # (the inner `git merge --no-ff` subprocess is invisible to the parent
    # Bash PreToolUse commit hook). No-op when --smm-dir is absent.
    smm_dir = Path(args.smm_dir) if args.smm_dir else None

    # ONE locked events read + ONE sprint load shared by both post-merge
    # consumers (the merge-event append below and trailer_gate.advisory),
    # replacing the prior double-read/double-load. Taken
    # BEFORE the append: the advisory's denominator excludes is_merge events and
    # the dedup scan only needs prior events, so one pre-append snapshot is
    # correct for both. Fail-open: if the locked read raises (LockTimeoutError
    # under parallel-teammate flock contention), shared_kwargs stays empty and
    # each consumer re-reads its own — never more fragile than the old baseline.
    shared_kwargs: dict = {}
    if smm_dir is not None:
        try:
            shared_events = _common.read_events_locked(smm_dir, "close-common-merge")
            shared_sprint = sprint_store.load_sprint_fail_open(smm_dir)
            shared_kwargs = {"events": shared_events, "sprint": shared_sprint}
        except Exception as exc:  # degrade to per-consumer reads, never abort
            sys.stderr.write(
                f"warn: shared merge read failed; each consumer re-reads ({exc})\n"
            )

    # Fail-open: this runs AFTER the merge commits but BEFORE push/delete, so
    # any failure (a LockTimeoutError under parallel-teammate flock contention,
    # an OSError on the dedup read or append) must never abort the close chain
    # and leave the source merged-but-unpushed. Catch broadly — the event is
    # accounting-only; its absence never breaks merge correctness.
    try:
        append_merge_commit_event(args.cwd, smm_dir, args.source, **shared_kwargs)
    except Exception as exc:  # accounting must never block the merge chain
        sys.stderr.write(f"warn: merge commit event skipped ({exc})\n")

    # Surface the Resolves-Event trailer ratio as a pre-merge advisory while
    # the un-trailered commits are still in reach. ADVISORY ONLY — it never
    # changes the return code; a sub-threshold ratio still merges. No-op when
    # --smm-dir is absent.
    if smm_dir is not None:
        # Fail-open: the advisory runs after the merge commits but before
        # push/delete, so NOTHING it does may abort the chain. Catch broadly —
        # beyond a print/encode error (UnicodeEncodeError is a ValueError) or a
        # broken stdout (OSError), advisory()'s locked event read can raise
        # LockTimeoutError (a plain Exception) under parallel-teammate flock
        # contention. The advisory is print-only by contract; it must never
        # change cmd_merge's exit code. Same fail-open posture as
        # append_merge_commit_event's guarded call above.
        try:
            note = trailer_gate.advisory(smm_dir, **shared_kwargs)
            if note:
                print(note)
        except Exception as exc:  # advisory must never block the merge chain
            sys.stderr.write(f"warn: trailer advisory skipped ({exc})\n")

    if git_remote.has_remote(args.cwd):
        rc = _run_or_relay(
            ["git", "push", "origin", args.target],
            cwd=args.cwd,
            success_msg=f"pushed: {args.target}",
        )
        if rc != 0:
            return rc

    if not branching.delete_branch(args.cwd, args.source, merge_target=args.target):
        # Source held by a teammate worktree → cleanup_teammate.py owns
        # deletion (worktree removal frees the branch). Don't abort the
        # chain — the merge + push already succeeded, and Step 7b's
        # cleanup will remove the branch when the worktree goes.
        if worktree.branch_held_by_worktree(args.cwd, args.source):
            print(f"skipped delete: {args.source} (held by worktree)")
            return 0
        sys.stderr.write(f"delete failed: {args.source}\n")
        return 1
    print(f"deleted: {args.source}")

    # Best-effort: prune the remote source ref too, so closed branches don't
    # accumulate on origin. A never-pushed source has no remote ref and the
    # delete fails harmlessly — rc is deliberately ignored (the merge + target
    # push already succeeded; this step never aborts the chain).
    # --no-verify: a pure ref deletion has nothing to gate, and the target
    # push above already fired any pre-push hook — don't re-run it.
    if git_remote.has_remote(args.cwd):
        r = subprocess.run(
            ["git", "push", "--no-verify", "origin", "--delete", args.source],
            cwd=args.cwd,
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print(f"deleted remote: {args.source}")
        else:
            print(f"remote source {args.source} already absent or unpushed")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared close-skill pipeline.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # All subcommands take --cwd; share via a parent parser.
    cwd_parent = argparse.ArgumentParser(add_help=False)
    cwd_parent.add_argument("--cwd", required=True)

    p = sub.add_parser(
        "preflight",
        parents=[cwd_parent],
        help="check worktree clean + current != target",
    )
    p.add_argument("--current", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser(
        "push",
        parents=[cwd_parent],
        help="push branch if remote exists, else skip",
    )
    p.add_argument("--branch", required=True)
    p.add_argument(
        "--smm-dir",
        default=None,
        help="SMM dir; required to relocate a teammate-worktree branch's push "
        "to the main checkout (resolves the base ref). Omit for solo pushes.",
    )
    p.set_defaults(func=cmd_push)

    p = sub.add_parser(
        "create-pr",
        parents=[cwd_parent],
        help="create PR via gh if available, else skip",
    )
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True)
    p.set_defaults(func=cmd_create_pr)

    p = sub.add_parser(
        "hook-present",
        parents=[cwd_parent],
        help="print 'present' or 'absent' for the project's git hooks",
    )
    p.set_defaults(func=cmd_hook_present)

    p = sub.add_parser(
        "diff-command",
        help="print the diff command the close-reviewer should run",
    )
    p.add_argument("--pr-output", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_diff_command)

    p = sub.add_parser(
        "close-review-gate",
        parents=[cwd_parent],
        help="emit RUN_FULL_CODE_REVIEW threshold flag for the cumulative close diff",
    )
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_close_review_gate)

    p = sub.add_parser(
        "merge",
        parents=[cwd_parent],
        help="chained merge --no-ff + push target (if remote) + delete source",
    )
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument(
        "--verify-gate",
        choices=("touch", "acceptance"),
        default=None,
        help="deterministic gate backstop (story=touch, sprint=acceptance); "
        "omit for plan/free close",
    )
    p.add_argument(
        "--smm-dir", default=None, help="SMM dir (required by --verify-gate)"
    )
    p.add_argument(
        "--force-verify",
        action="store_true",
        help="bypass the acceptance gate (sprint-close --force-close path)",
    )
    p.add_argument(
        "--review-clean-cwd",
        default="",
        help="after-review clean re-check target (story-close teammate worktree); "
        "refuse the merge if dirty so an uncommitted reviewer fix isn't discarded "
        "by worktree cleanup. Empty (solo/other closes) skips the check.",
    )
    p.set_defaults(func=cmd_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
