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

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import execution_plan_store

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


def write_system_context(smm_dir: Path, stage: int) -> None:
    """Write a minimal system_context.json with the given branching stage."""
    ctx = {"project_name": "test", "branching_strategy": {"stage": stage}}
    (smm_dir / "system_context.json").write_text(json.dumps(ctx))


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
