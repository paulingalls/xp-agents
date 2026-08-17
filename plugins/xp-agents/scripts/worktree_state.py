#!/usr/bin/env python3
"""What is dirty in a checkout right now — the working-tree question, alone.

Split out of `commits.py` when that module crossed its 450-line sub-cap.
Two open concerns had recorded the prediction that it would, and that the
answer was "a real extraction, not another trim": a previous close had already
landed it at 449 of 450, one line of headroom. Two stories merging in one
sprint took it to 460, so the extraction is taken here instead of being paid
for a fifth time. (Ids omitted deliberately — an emitter carrying a 12-hex
event id is what test_no_historical_ids_in_emitters exists to catch.)

Cohesive by question rather than by convenience. Everything here answers "what
is uncommitted?" and carries its own vocabulary to do it — the three scan
commands plus the O(1) repo probe that tells "no repo to ask about" apart from
"this scan timed out", a distinction the rest of `commits.py` never needs. Its
readers are the TDD gate (`tdd_check`), the commit-size advisory
(`commit_handling`) and the post-commit nudge (`bash_post_tool`).

The general git readers it leans on stay in `commits.py`, so the dependency runs
one way and there is no cycle.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import code_files
from commits import _nul_paths, _run_git

__all__ = [
    "get_uncommitted_code_files",
    "get_uncommitted_files",
]


_GIT_STAGED = ["git", "diff", "--cached", "--name-only", "-z"]
_GIT_UNSTAGED = ["git", "diff", "--name-only", "-z"]
_GIT_UNTRACKED = ["git", "ls-files", "--others", "--exclude-standard", "-z"]
# O(1) repo probe — unlike the scans above it does not walk the worktree, so it
# still answers when they time out. That asymmetry is the whole point: it tells
# "no repo to ask about" apart from "this scan failed".
_GIT_IS_REPO = ["git", "rev-parse", "--is-inside-work-tree"]


def _changed_paths(cwd: str, cmds: list[list[str]]) -> set[str] | None:
    """Union of the path lines emitted by several git commands.

    None (not an empty set) when any git call failed, so callers can tell
    "git could not answer" apart from "nothing changed".
    """
    paths: set[str] = set()
    for cmd in cmds:
        out = _run_git(cmd, cwd)
        if out is None:
            return None
        paths.update(_nul_paths(out))
    return paths


def get_uncommitted_files(cwd: str) -> list[str] | None:
    """Every code file in flight in the working tree: staged, unstaged, OR
    untracked. Test files INCLUDED. This is the "is the tree dirty?" signal.

    Deliberately wider than ``get_uncommitted_code_files``, which answers a
    different question ("is a commit of *production* code warranted?") and so
    drops test files. Dirtiness must not: a tree dirty with only a broken test
    file is still broken work in flight, and an untracked brand-new failing
    test is the single most common shape of the TDD red step. Both read as
    CLEAN under the narrower helper — which, for the TDD gate
    (``tdd_check.find_last_test_signal``), is the disarm direction.

    Two ways to not get an answer, and they must not be conflated:

    * **There is no repo** (git absent, or not a work tree). Structural and
      permanent. Reads as CLEAN — a project git cannot answer for at all must
      not gate on a prior-session failure forever.
    * **This scan failed** (timeout). Transient, and the untracked scan walks
      the WHOLE worktree, so it is by far the likeliest ``_run_git`` timeout
      here. Returns **None** = "could not answer". Collapsing that to "no
      files" reads as a clean tree and UN-GATES a real failure, so the caller
      must be able to fail safe.

    The O(1) repo probe discriminates them: it still answers when a
    worktree-walking scan times out.
    """
    paths = _changed_paths(cwd, [_GIT_STAGED, _GIT_UNSTAGED, _GIT_UNTRACKED])
    if paths is None:
        if _run_git(_GIT_IS_REPO, cwd) is None:
            return []
        return None
    return sorted(f for f in paths if code_files.is_code_file(f))


def get_uncommitted_code_files(cwd: str) -> list[str]:
    """Get non-test code files with uncommitted changes (staged + unstaged).

    Used by the post-green-tests nudge to determine if a commit is warranted.
    Returns empty list on any git failure.
    """
    paths = _changed_paths(cwd, [_GIT_STAGED, _GIT_UNSTAGED])
    if not paths:
        return []

    from pre_tool_write import is_test_file

    return [
        f for f in sorted(paths) if code_files.is_code_file(f) and not is_test_file(f)
    ]
