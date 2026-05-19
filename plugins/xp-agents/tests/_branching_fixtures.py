#!/usr/bin/env python3
"""Shared test fixtures for git+SMM tests.

Canonical home for hermetic repo setup. ``init_repo`` pins ``-b main``
so tests pass on CI runners whose ``init.defaultBranch`` defaults to
``master``, configures a deterministic git identity, and creates one
empty initial commit. Any test that needs a temporary git repo should
import from here rather than reproduce the boilerplate inline.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import execution_plan_store
from _system_context_fixtures import valid_doc

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
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


def write_system_context(smm_dir: Path, stage: int, **bs_extras: object) -> None:
    """Write a fully-valid system_context.json with the given branching stage.

    Extra ``branching_strategy`` fields (``integration_branch``,
    ``protected_branches``, ...) pass through ``bs_extras``. Single
    fixture for all stage/branching test shapes — replaces near-identical
    inline ``_write_stage_3_ctx`` / ``_write_branching_ctx`` helpers
    that drifted across test classes.

    Uses ``valid_doc`` so the doc passes schema validation on save. The
    earlier minimal shape (project_name + branching_strategy only) failed
    save validation, which ``_maybe_auto_promote``'s broad except silently
    swallowed — masking the real auto-promote behavior in every test.

    Note for stage=1 callers: the auto-promote will fire on the first
    ``get_branching_stage`` read, mutating this fixture to stage=2 and
    emitting one ``decision`` event with topic ``branching-stage-auto-promote``.
    Tests that assert on event-log contents must account for this; use
    ``stage=2`` directly when the test is not specifically exercising the
    auto-promote path.
    """
    doc = valid_doc(branching_strategy={"stage": stage, **bs_extras})
    (smm_dir / "system_context.json").write_text(json.dumps(doc))


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


def seed_sprint_with_stories(smm_dir: Path, stories: "list[tuple[str, str]]") -> None:
    """Write a minimal sprint.json from ``[(story_id, status), ...]`` pairs.

    Single-source-of-truth fixture — replaces three near-identical
    helpers (test_worktree.py, test_branching_cli_detection.py,
    test_story_close.py) that built the same sprint shape with slight
    naming drift (`_write_sprint` vs `_write_sprint_with_stories`).
    """
    story_dicts = [
        {
            "id": sid,
            "title": f"t-{sid}",
            "status": status,
            "dependencies": [],
            "milestone_ref": "",
            "design_sources": "",
            "context": "",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": [],
        }
        for sid, status in stories
    ]
    (smm_dir / "sprint.json").write_text(
        json.dumps(
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-05-04",
                "milestone": "",
                "stories": story_dicts,
            }
        )
    )


def seed_plan(smm_dir: Path, branch: str | None = None) -> None:
    """Write a minimal valid execution_plan.json. Optionally sets the branch field."""
    plan = {
        "title": "Test Plan",
        "sources": [],
        "overview": "ov",
        "milestones": [],
    }
    if branch is not None:
        plan["branch"] = branch
    execution_plan_store.save_plan(smm_dir, plan, enforce_budget=False)


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
    :func:`add_bare_remote` first — ``--set-upstream-to`` requires a
    configured ``origin``.
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
