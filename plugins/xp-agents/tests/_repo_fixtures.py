#!/usr/bin/env python3
"""Hermetic git-repo setup and commit fixtures.

Split out of ``_branching_fixtures.py`` (split-shim per convention
91fcf9b8744d) when that file crossed the 500-line cap. Canonical home for
hermetic repo setup: ``init_repo`` pins ``-b main`` so tests pass on CI
runners whose ``init.defaultBranch`` defaults to ``master``, configures a
deterministic git identity, and creates one empty initial commit. Any test
that needs a temporary git repo should import from here rather than
reproduce the boilerplate inline.

Owns ``GIT_ENV`` and imports DOWN from ``_branch_probes`` (``make_commit``
returns the resulting SHA). ``_branch_probes`` must never import from here,
or the split becomes a cycle.

Callers should keep importing from ``_branching_fixtures``, which re-exports
every name below by identity.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _branch_probes import get_head_sha

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def init_repo(td: str) -> None:
    """Create a fresh git repo with one empty initial commit on `main`.

    Pin the initial branch to `main` so tests are hermetic across runners
    that ship different `init.defaultBranch` configs (CI runners often
    default to `master`). branching.get_primary_branch returns `main` at
    Stages 0-2; the fixture must match.

    Requires git >= 2.28 for the `-b` flag (released July 2020).
    """
    subprocess.run(["git", "init", "-b", "main", td], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=td,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=td,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=td,
        capture_output=True,
        check=True,
        env=GIT_ENV,
    )


def init_repo_with_ignored_worktrees(td: str) -> None:
    """Init a repo and seed it for acceptance-env tests.

    Builds on ``init_repo`` then commits a ``.gitignore`` that excludes
    ``.claude/worktrees/`` plus a ``base.txt``, so the main tree stays clean
    once a teammate worktree is created under the gitignored path (mirrors
    production). Shared by the acceptance-env lib + CLI suites, which both
    detach/conflict-merge HEAD and so need a clean-room repo per test.
    """
    init_repo(td)
    (Path(td) / ".gitignore").write_text(".claude/worktrees/\n")
    (Path(td) / "base.txt").write_text("base\n")
    subprocess.run(
        ["git", "add", ".gitignore", "base.txt"],
        cwd=td,
        env=GIT_ENV,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=td,
        env=GIT_ENV,
        capture_output=True,
        check=True,
    )


def init_repo_in_spaced_parent(parent: str, repo_name: str = "repo") -> str:
    """Init a fresh git repo under ``<parent>/has space/<repo_name>`` and
    return its path. Used by tests that need a worktree at a path with a
    space in it — tempfile.mkdtemp's path never contains spaces, so the
    space must be injected via a custom subdir layered on top.
    """
    spaced = Path(parent) / "has space"
    spaced.mkdir()
    repo = spaced / repo_name
    repo.mkdir()
    init_repo(str(repo))
    return str(repo)


def make_conflicted_merge(repo: str, env: dict = GIT_ENV) -> None:
    """Leave ``repo`` with an in-progress conflicted merge (MERGE_HEAD set).

    Two branches edit the same line of ``base.txt`` (which the caller must have
    committed), then ``git merge`` fails leaving the merge in progress on branch
    B. Guards with plain ``assert`` that the merge actually conflicted so a
    future non-conflicting edit can't silently make recovery tests vacuous.
    """

    def _g(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=repo, env=env, capture_output=True, text=True
        )

    _g("checkout", "-b", "A")
    (Path(repo) / "base.txt").write_text("A change\n")
    _g("commit", "-am", "A edit")
    _g("checkout", "main")
    _g("checkout", "-b", "B")
    (Path(repo) / "base.txt").write_text("B change\n")
    _g("commit", "-am", "B edit")
    r = _g("merge", "A")
    assert r.returncode != 0, "merge was expected to conflict"
    assert (Path(repo) / ".git" / "MERGE_HEAD").exists()


def create_teammate_worktree_with_commit(
    repo_cwd: str,
    story_id: str,
    env: dict,
    *,
    content: str | None = None,
) -> str:
    """Create a teammate worktree under repo_cwd with one real commit.

    Shared shape used by capstone integration tests that need to verify
    teammate close + merge composition. Returns the absolute worktree path.

    `content` overrides the default body for the teammate's feature file —
    set distinct content per branch when the test exercises a merge
    conflict (default content is per-story but identical across branches
    when caller doesn't specify).
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import spawn_teammate

    wt_path = spawn_teammate.create_worktree(f"worktree-{story_id}", repo_cwd)
    feature = Path(wt_path) / f"{story_id}-feature.txt"
    feature.write_text(content if content is not None else f"work for {story_id}")
    subprocess.run(
        ["git", "add", feature.name],
        cwd=wt_path,
        env=env,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"[{story_id}] add feature"],
        cwd=wt_path,
        env=env,
        capture_output=True,
        check=True,
    )
    return wt_path


def merge_teammate_branch(
    repo_cwd: str,
    source: str,
    target: str,
    env: dict,
) -> subprocess.CompletedProcess:
    """Run close_common.py merge from the orchestrator cwd.

    Merge MUST run at orchestrator cwd (not at the teammate's worktree
    cwd) — git merge checks out the target branch which the orchestrator
    already holds; running from the teammate's cwd fails with "target is
    already used by worktree at <orch>". close_common skips the
    post-merge source-branch delete when the source is held by a live
    teammate worktree (cleanup_teammate.py owns that step).
    """
    close_common = Path(__file__).parent.parent / "scripts" / "close_common.py"
    return subprocess.run(
        [
            sys.executable,
            str(close_common),
            "merge",
            "--cwd",
            repo_cwd,
            "--source",
            source,
            "--target",
            target,
        ],
        cwd=repo_cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def run_accept_env(
    smm_dir: Path,
    cwd: str,
    *args: str,
    env: dict = GIT_ENV,
) -> subprocess.CompletedProcess:
    """Run `branching.py accept-env <args>` at ``cwd``.

    Single-source-of-truth wrapper for the acceptance-env prepare/restore
    subprocess calls — replaces the byte-identical ``_accept_env`` method
    duplicated across the story-002 main-checkout accept test classes
    (TestTeammateAcceptMainCheckout, TestMultiStoryPrepareRestore).
    """
    branching_py = Path(__file__).parent.parent / "scripts" / "branching.py"
    return subprocess.run(
        [
            sys.executable,
            str(branching_py),
            "--smm-dir",
            str(smm_dir),
            "accept-env",
            *args,
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def make_commit(
    cwd: str,
    branch: str,
    filename: str,
    content: str,
    message: str,
) -> str:
    """Checkout `branch` (creating it), write filename+content, commit, return SHA.

    Used by integration tests that need to fabricate branch state for
    merge/cleanup verification.
    """
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    (Path(cwd) / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=cwd, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd,
        capture_output=True,
        check=True,
        env=GIT_ENV,
    )
    return get_head_sha(cwd)


def append_commit(cwd: str, filename: str = "feature.txt") -> None:
    """Write filename and commit on the current branch (no checkout).

    Counterpart to ``make_commit`` for tests that need to advance HEAD on
    whatever branch is currently checked out.
    """
    (Path(cwd) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=cwd,
        capture_output=True,
        check=True,
        env=GIT_ENV,
    )


def add_bare_remote(td: str, remote_name: str = "origin") -> str:
    """Initialize a bare git repo INSIDE `td` and add it as a remote.

    Placing the bare repo under `td` ensures cleanup with the parent
    TemporaryDirectory — no leaked `*-bare.git` dirs in $TMPDIR.
    Returns the bare repo path.
    """
    bare = str(Path(td) / "remote.git")
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", bare],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", remote_name, bare],
        cwd=td,
        capture_output=True,
        check=True,
    )
    return bare


def add_pre_push_hook(
    td: str, marker_name: str = "pre_push_fired", *, block: bool = True
) -> Path:
    """Install an executable ``.git/hooks/pre-push`` that records its firing.
    Returns the marker Path. The marker does NOT exist until the hook fires.

    Lets behavioral tests prove ``--no-verify`` actually suppresses the
    project pre-push hook end-to-end, rather than only asserting the push
    argv. The absolute marker path is baked in, so it lands regardless of the
    hook's cwd.

    ``block=True`` (default): on fire the hook ``touch``es the marker and exits
    non-zero — a test asserts both "hook fired" (marker exists) and "push
    blocked" (returncode != 0).

    ``block=False``: the exit-0 variant appends the pushed refs (the hook's
    stdin — one ``<local-ref> <local-sha> <remote-ref> <remote-sha>`` line per
    ref, ``(delete)`` as the local ref for a deletion) to the marker and exits
    zero, letting the push proceed. A test inspects the log to tell WHICH push
    fired the hook — e.g. that a ``--no-verify`` delete push left no
    ``(delete)`` line while an ordinary push was recorded.
    """
    marker = Path(td) / marker_name
    hook = Path(td) / ".git" / "hooks" / "pre-push"
    if block:
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
    else:
        hook.write_text(f'#!/bin/sh\ncat >> "{marker}"\nexit 0\n')
    hook.chmod(0o755)
    return marker
