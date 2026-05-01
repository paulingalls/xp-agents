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

import branching
import git_hooks


def pre_commit_hook_present(repo_root: str) -> bool:
    """Return True when the project runs tests via a git hook on commit/push.

    Strict — defers to ``git_hooks.will_fire_hook`` (markers + executable
    pre-commit/pre-push, honoring ``core.hooksPath``). Non-executable
    scripts and ``.sample`` files don't qualify because git won't fire them.
    """
    return git_hooks.will_fire_hook(repo_root)


def _has_remote(cwd: str) -> bool:
    result = subprocess.run(["git", "remote"], cwd=cwd, capture_output=True, text=True)
    return bool(result.stdout.strip())


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
    if not _has_remote(args.cwd):
        print("skipped: no remote configured")
        return 0
    return _run_or_relay(
        ["git", "push", "-u", "origin", args.branch],
        cwd=args.cwd,
        success_msg=f"pushed: {args.branch}",
    )


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


def cmd_merge(args: argparse.Namespace) -> int:
    """Chained merge --no-ff + (push target if remote) + delete source.

    Any step failing aborts the chain — no push or delete on merge
    failure, no delete on push failure. Source branch always survives
    a failed step so the user can resolve and retry.

    branching.merge_branch sys.exit(1)s on conflict (with git's stderr
    already emitted), so we trust it to bail. delete_branch returns
    False on failure (e.g. unmerged commits) — we surface and abort.
    """
    branching.merge_branch(args.cwd, args.source, target=args.target)
    print(f"merged: {args.source} -> {args.target}")

    if _has_remote(args.cwd):
        rc = _run_or_relay(
            ["git", "push", "origin", args.target],
            cwd=args.cwd,
            success_msg=f"pushed: {args.target}",
        )
        if rc != 0:
            return rc

    if not branching.delete_branch(args.cwd, args.source):
        sys.stderr.write(f"delete failed: {args.source}\n")
        return 1
    print(f"deleted: {args.source}")
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
        "merge",
        parents=[cwd_parent],
        help="chained merge --no-ff + push target (if remote) + delete source",
    )
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
