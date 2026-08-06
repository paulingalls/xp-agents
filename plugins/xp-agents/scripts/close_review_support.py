#!/usr/bin/env python3
"""Read-only review-support commands for the close-skill pipeline.

Split out of close_common.py (story-002) when that module crossed the
500-line cap while adding `merge --archive-sprint`. These three commands
don't mutate git state — they drive the review step the close skills run
before merging: close-review-gate (sizing threshold for the full
/code-review), diff-command (the merged-range diff the reviewer must
review), and hook-present (detects a project test-running git hook).
close_common.py's `merge`/`push`/`preflight`/`create-pr` stay there; this
mirrors the existing test split (test_close_common_review_support.py vs
test_close_common_pipeline.py).
"""

import argparse
import sys
from pathlib import Path

# Resolve sibling/smm modules without modifying caller sys.path.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import commits
import git_hooks


def pre_commit_hook_present(repo_root: str) -> bool:
    """Return True when the project runs tests via a git hook on commit/push.

    Strict — defers to ``git_hooks.will_fire_hook``: an executable
    pre-commit/pre-push in the resolved hooks dir, honoring
    ``core.hooksPath``. Non-executable scripts and ``.sample`` files don't
    qualify because git won't fire them, and neither does a framework config
    file on its own — ``lefthook.yml`` present but never installed means this
    merge runs nothing, which is exactly when the caller's guidance block
    needs to appear.
    """
    return git_hooks.will_fire_hook(repo_root)


def cmd_hook_present(args: argparse.Namespace) -> int:
    """Print 'present' or 'absent' for the close-skill preloads."""
    print("present" if pre_commit_hook_present(args.cwd) else "absent")
    return 0


def cmd_diff_command(args: argparse.Namespace) -> int:
    """Print `git diff <target>...<source>` — the range the merge actually lands.

    Invariant: **the review source is the ref that merges; the PR head is never
    the review source.** cmd_merge merges a LOCAL ref (`<source>`), while the PR
    head is only the REMOTE head as of Step 2's push — close-time fixes (Step 4b
    validate-and-fix, Step 5c "fix now") land on `<source>` AFTER that push and
    still ship in the merge, so reviewing `gh pr diff <N>` would miss them
    (live at sprint-118). The PR is still created (Step 3) as the human record
    and push target; only its role as review INPUT is removed.

    Not `...HEAD`: at story-close this runs from the ORCHESTRATOR checkout,
    where HEAD is the sprint branch, not the story branch. Naming `<source>` is
    cwd-independent (worktrees share the object store and refs). Three-dot
    matches the sizing gate (commits.get_code_files_in_range).
    """
    print(f"git diff {args.target}...{args.source}")
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
