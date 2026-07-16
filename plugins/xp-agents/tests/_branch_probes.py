#!/usr/bin/env python3
"""Branch and SHA probes for git-backed tests.

Split out of ``_branching_fixtures.py`` (split-shim per convention
91fcf9b8744d) when that file crossed the 500-line cap. This module answers
"where is this ref?" and manipulates refs directly; it deliberately holds no
``GIT_ENV`` and imports nothing from its sibling fixture modules, so it sits
at the bottom of the split's dependency order — ``_repo_fixtures`` imports
DOWN from here, never the reverse.

Callers should keep importing from ``_branching_fixtures``, which re-exports
every name below by identity.
"""

import subprocess


def get_current_branch(cwd: str) -> str:
    """Return the current branch name (HEAD short ref)."""
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip()


def get_head_sha(cwd: str) -> str:
    """Return the current HEAD commit SHA."""
    return get_branch_sha(cwd, "HEAD")


def get_branch_sha(cwd: str, ref: str) -> str:
    """Return the commit SHA `ref` points at, or "" when it resolves to nothing.

    The assertion for "did this branch MOVE?" — the resume arm's silent failures
    (an unresolvable base, a base that fast-forwards a story branch onto primary)
    are invisible in a return value and only show up in where the ref ends up.
    """
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_log_oneline_at(cwd: str, branch: str) -> str:
    """Return `git log --oneline <branch>` output at cwd.

    Used by integration tests that need to assert which commits landed on
    a target branch after merge composition.
    """
    return subprocess.run(
        ["git", "log", "--oneline", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def get_current_branch_at(cwd) -> str:
    """Run `git rev-parse --abbrev-ref HEAD` at ``cwd``. Single-source-of-
    truth for tests that need the orchestrator's (or a worktree's) HEAD
    branch — replaces inline `_orchestrator_branch` helpers previously
    duplicated across TestStoryClosePreloadTeammateDetection and
    TestM2TeammateAcceptFlow.
    """
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def make_branch(cwd: str, name: str) -> None:
    """Cut local branch `name` at HEAD without checking it out.

    Arms the RESUME arm of _create_or_resume_branch, and seeds the sprint
    branch a story base resolves to. `name` must match what the code under
    test will compute — a story branch the code names differently is simply
    not found, and the test quietly exercises the CREATE arm instead. When
    the code path runs in a subprocess, derive the namespace from
    `identity.user_namespace(cwd)` (git config), never a hardcoded one.
    """
    subprocess.run(["git", "branch", name], cwd=cwd, capture_output=True, check=True)


def branch_exists(cwd: str, name: str) -> bool:
    """Return True if `name` is a local git branch in `cwd`. Test helper."""
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", name],
            cwd=cwd,
            capture_output=True,
        ).returncode
        == 0
    )


def diverge_tracking_ref(td: str, branch: str) -> None:
    """Point ``refs/remotes/origin/<branch>`` at ``<branch>~1`` and bind
    the local branch to it as upstream.

    Reproduces the worktree-teammate state that breaks ``git branch -d``:
    teammate pushed an early commit, then advanced the branch locally;
    the merge target now holds the merge commit but the local tracking
    ref still points at the older push. Caller must run
    :func:`add_bare_remote` (``_repo_fixtures``) first —
    ``--set-upstream-to`` requires a configured ``origin``.
    """
    base_sha = subprocess.run(
        ["git", "rev-parse", f"{branch}~1"],
        cwd=td,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{branch}", base_sha],
        cwd=td,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "branch", f"--set-upstream-to=origin/{branch}", branch],
        cwd=td,
        capture_output=True,
        check=True,
    )


def remote_has_branch(cwd: str, branch: str, remote: str = "origin") -> bool:
    """True iff `branch` exists on `remote` (asks the remote via ls-remote)."""
    r = subprocess.run(
        ["git", "ls-remote", "--heads", remote, branch],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return branch in r.stdout


def checkout_main(cwd: str) -> None:
    """Checkout `main` in `cwd`. Used by tests that leave a just-created
    branch and re-invoke a create_*_branch wrapper to test the resume path."""
    subprocess.run(
        ["git", "checkout", "main"], cwd=cwd, capture_output=True, check=True
    )
