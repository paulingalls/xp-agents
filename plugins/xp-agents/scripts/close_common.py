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
import branching
import code_files
import commit_handling
import commits
import git_hooks
import git_remote
import identity
import sprint_store
import verify_acceptance
import verify_paths
import worktree
from event_schema import METADATA_KEY_COMMIT_HASH


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


def _verify_gate_block(args: argparse.Namespace) -> str | None:
    """Deterministic close-gate backstop: re-derive the gate signal and return
    a refusal reason, or None to proceed.

    Defends against an LLM that skips the SKILL prose gate. Both gates fail
    CLOSED on their own signal; on git/SMM errors the touch gate fails OPEN
    (matching verify_paths' established contract — an unreadable range can't
    block a legitimate merge, and a broken ref would fail the merge anyway).

    Inert when no --verify-gate (plan/free close). Refuses (rather than
    silently no-op'ing) when --verify-gate is set without --smm-dir: a
    misconfigured invocation must not invisibly disable the backstop.
    """
    if not args.verify_gate:
        return None
    if not args.smm_dir:
        return "merge refused: --verify-gate requires --smm-dir"
    smm_dir = Path(args.smm_dir)

    match args.verify_gate:
        case "touch":
            # Self-derived from sprint.json + git: refuse when the story's
            # declared acceptance-test paths are untouched on target..source
            # and no [verify-deferred] commit defers them.
            story_id = identity.extract_story_id(args.source)
            if not story_id:
                return None
            try:
                story = sprint_store.get_story(smm_dir, story_id)
            except sprint_store.SprintCorruptError as exc:
                return f"merge refused: sprint.json is corrupt or schema-invalid: {exc}"
            except (ValueError, OSError):
                return None  # missing sprint/story (or symlink) → fail open
            paths = verify_paths.extract_verify_paths(story)
            if not paths:
                return None
            try:
                untouched = verify_paths.untouched_verify_paths(
                    paths, args.cwd, base=args.target, head=args.source
                )
            except ValueError:
                return None  # fail open: unreadable range can't block
            if untouched and not commit_handling.branch_has_verify_deferred(
                args.cwd, args.target, head=args.source
            ):
                return (
                    f"merge refused: no commit on {args.target}..{args.source} "
                    f"touched {untouched}; add a touching commit or commit with "
                    "[verify-deferred] <reason>"
                )
            return None

        case "acceptance":
            # Reads the last sprint-verify event (cwd-independent): refuse on
            # red unless the SKILL passed --force-verify (the --force-close path,
            # which already recorded the bypass as debt).
            try:
                sprint = sprint_store.load_sprint(smm_dir)
            except sprint_store.SprintCorruptError as exc:
                return f"merge refused: sprint.json is corrupt or schema-invalid: {exc}"
            except OSError:
                return None  # symlinked sprint path → fail open (matches touch gate)
            if sprint is None:
                return None
            status, failing = verify_acceptance._last_verify(
                smm_dir, sprint["sprint_id"]
            )
            if status == verify_acceptance.VERIFY_STATUS_RED and not args.force_verify:
                items = ", ".join(
                    f"{r.get('story', '?')} {r.get('command', '')}" for r in failing
                )
                return (
                    "merge refused: sprint acceptance is red: "
                    f"{items}; fix and re-run /xp-sprint-review, or "
                    "/xp-sprint-close --force-close <reason>"
                )
            return None

    return None


def _append_merge_commit_event(cwd: str, smm_dir: Path | None, source: str) -> None:
    """Append a type=commit event for the merge HEAD just produced by
    ``branching.merge_branch``.

    Closes the merge-gap commit-event hole: the parent Bash PreToolUse hook
    only matches top-level ``git commit`` shells, so the inner
    ``git merge --no-ff`` subprocess spawned by ``branching.merge_branch``
    leaves no event. We emit one here mirroring
    ``commit_handling._handle_commit``'s metadata shape (action, code_commit,
    code_file_count, commit_hash, story_id, sprint_id) so downstream
    accounting (commit counts, story attribution, resolves-link rate) sees
    close-cycle merges.

    No-op when ``smm_dir`` is None — some close-skill callers don't pass
    ``--smm-dir`` yet. Dedupes by ``commit_hash`` so a retried/"Already up to
    date" re-merge cannot double-emit.
    """
    if smm_dir is None:
        return
    commit_hash = commits.get_head_commit_hash(cwd)
    if not commit_hash:
        return
    events, _ = _common.load_events_with_resolutions(smm_dir)
    if any(
        e.get("type") == _common.COMMIT
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    ):
        return
    files = commits.get_committed_files(cwd)
    body = commits.get_commit_message_body(cwd) or f"Merge {source}"
    code_file_count = sum(1 for f in files if code_files.is_code_file(f))
    # Degrade gracefully on a corrupt/schema-invalid sprint.json: the merge
    # itself already succeeded on target, and the surrounding push/delete/
    # remote-prune chain must continue. Matches _verify_gate_block's
    # established fail-open posture for SMM-state errors here.
    try:
        sprint = sprint_store.load_sprint(smm_dir)
    except (sprint_store.SprintCorruptError, OSError):
        sprint = None
    # is_merge=True excludes this event from resolves_link_rate accounting:
    # the merge HEAD aggregates already-recorded story commits, each of
    # which carries its own Resolves trailer. Counting the merge commit
    # in the denominator would dilute the rate without a meaningful
    # numerator (merge commit messages don't carry Resolves trailers).
    event = commit_handling.make_commit_event(
        "close_common",
        body,
        commit_hash=commit_hash,
        files=files,
        code_file_count=code_file_count,
        story_id=identity.extract_story_id(source),
        sprint_id=sprint["sprint_id"] if sprint is not None else None,
        is_merge=True,
    )
    _common.bulk_append_safe(smm_dir, [event])


def cmd_merge(args: argparse.Namespace) -> int:
    """Chained merge --no-ff + (push target if remote) + delete source.

    Any step failing aborts the chain — no push or delete on merge
    failure, no delete on push failure. Source branch always survives
    a failed step so the user can resolve and retry.

    A deterministic verify-gate backstop runs FIRST (before merge), so a
    skipped SKILL prose gate can't merge an untouched/red story. See
    _verify_gate_block.

    branching.merge_branch sys.exit(1)s on conflict (with git's stderr
    already emitted), so we trust it to bail. delete_branch returns
    False on failure (e.g. unmerged commits) — we surface and abort.
    """
    block = _verify_gate_block(args)
    if block:
        sys.stderr.write(block + "\n")
        return 1

    branching.merge_branch(args.cwd, args.source, target=args.target)
    print(f"merged: {args.source} -> {args.target}")

    # Emit a commit event for the merge HEAD; closes the merge-gap hole
    # (the inner `git merge --no-ff` subprocess is invisible to the parent
    # Bash PreToolUse commit hook). No-op when --smm-dir is absent.
    _append_merge_commit_event(
        args.cwd, Path(args.smm_dir) if args.smm_dir else None, args.source
    )

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
    p.set_defaults(func=cmd_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
