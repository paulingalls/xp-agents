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


def write_system_context(smm_dir: Path, stage: int) -> None:
    """Write a fully-valid system_context.json with the given branching stage.

    Uses `valid_doc` so the doc passes schema validation on save. The
    earlier minimal shape (project_name + branching_strategy only) failed
    save validation, which `_maybe_auto_promote`'s broad except silently
    swallowed — masking the real auto-promote behavior in every test.

    Note for stage=1 callers: the auto-promote will fire on the first
    `get_branching_stage` read, mutating this fixture to stage=2 and
    emitting one `decision` event with topic `branching-stage-auto-promote`.
    Tests that assert on event-log contents must account for this; use
    `stage=2` directly when the test is not specifically exercising the
    auto-promote path.
    """
    doc = valid_doc(branching_strategy={"stage": stage})
    (smm_dir / "system_context.json").write_text(json.dumps(doc))


def get_current_branch_at(cwd) -> str:
    """Run `git rev-parse --abbrev-ref HEAD` at ``cwd``. Single-source-of-
    truth for tests that need the orchestrator's (or a worktree's) HEAD
    branch — both TestStoryClosePreloadTeammateDetection and
    TestM2TeammateAcceptFlow had identical inline `_orchestrator_branch`
    helpers; this collapses them.
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
