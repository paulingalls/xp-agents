#!/usr/bin/env python3
"""Temp-git-repo scaffolding: the base case that drives the shell entry points.

`_TempRepoTestCase` gives a suite an isolated git repo + plugin-data dir per test
CLASS, so subprocess tests of `init.sh` / `append.sh` can never touch the real SMM.
`cleanup_test_worktrees` tears down the worktrees a test created.

Split out of `_bases` when that file crossed the 500-line ceiling. Both names are
re-exported from `_bases` (and thence conftest) BY IDENTITY, so every existing
import spelling still resolves to these objects — the unchanged suites are the
verification that the move is behavior-preserving.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import _PLUGIN_ROOT


class _TempRepoTestCase(unittest.TestCase):
    """Base class: creates an isolated temp git repo per test class.

    Prevents subprocess tests (init.sh, append.sh) from touching the real SMM.
    """

    _INIT_SH = _PLUGIN_ROOT / "smm" / "init.sh"
    _APPEND_SH = _PLUGIN_ROOT / "smm" / "append.sh"

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp())
        cls._plugin_data_dir = Path(tempfile.mkdtemp())
        cls._test_env = os.environ.copy()
        cls._test_env["XP_AGENTS_DATA"] = str(cls._plugin_data_dir)
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=cls.tmpdir,
            capture_output=True,
            check=True,
            env=cls._test_env,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=cls.tmpdir,
            capture_output=True,
            env=cls._test_env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=cls.tmpdir,
            capture_output=True,
            env=cls._test_env,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._plugin_data_dir, ignore_errors=True)
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _run_init(
        cls,
        extra_env: dict | None = None,
        unset: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        """Run init.sh in the class temp repo.

        `unset` removes vars from the inherited env. `extra_env` can only
        override, never remove — and setUpClass pins the SMM data root, so a
        test asserting "this var is ABSENT" cannot express that without it.
        """
        env = cls._test_env.copy()
        if extra_env:
            env.update(extra_env)
        for var in unset:
            env.pop(var, None)
        return subprocess.run(
            [str(cls._INIT_SH)],
            capture_output=True,
            text=True,
            cwd=str(cls.tmpdir),
            env=env,
        )

    @classmethod
    def _get_smm_dir(cls) -> Path:
        if not hasattr(cls, "_smm_dir_cache"):
            result = cls._run_init()
            assert result.returncode == 0, f"init.sh failed: {result.stderr}"
            cls._smm_dir_cache = Path(result.stdout.strip())
            # Inject SMM_DIR into the test env so subsequent subprocess calls
            # skip the init.sh round-trip (init.sh honors $SMM_DIR).
            cls._test_env["SMM_DIR"] = str(cls._smm_dir_cache)
        return cls._smm_dir_cache

    @classmethod
    def _run_append(cls, *args: str) -> subprocess.CompletedProcess:
        env = cls._test_env.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
        return subprocess.run(
            [str(cls._APPEND_SH), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cls.tmpdir),
        )

    @classmethod
    def _events_file(cls) -> Path:
        return cls._get_smm_dir() / "events.jsonl"

    @classmethod
    def _read_events(cls) -> list[dict]:
        """Parse events.jsonl as a list of event dicts; skip blank lines."""
        return [
            json.loads(line)
            for line in cls._events_file().read_text().splitlines()
            if line.strip()
        ]

    @classmethod
    def _clear_events(cls) -> None:
        cls._events_file().write_text("")


def cleanup_test_worktrees(tmpdir: Path, prefix: str = "teammate-") -> None:
    """Remove all worktrees matching prefix. For test tearDown."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("worktree ") and prefix in line:
            wt = line.split("worktree ", 1)[1]
            subprocess.run(
                ["git", "worktree", "remove", "--force", wt],
                cwd=tmpdir,
                capture_output=True,
            )


def _create_teammate_worktree(
    tmpdir: Path, name: str, branch: str | None = None
) -> str:
    """Create a worktree with a commit. Returns worktree path.

    `name` is the worktree directory name. `branch` defaults to `name`
    (matching the legacy assumption); pass a different value to model the
    real-world case where the worktree dir name (e.g. ``worktree-story-007``)
    differs from the checked-out branch (e.g. ``paulingalls/story-007-perf``).

    Imports `worktree` lazily: this module is pulled in by `_bases` before
    conftest inserts scripts/ onto sys.path (see conftest.py's import order),
    so a module-level `import worktree` here would fail at conftest load.
    """
    import worktree

    branch = branch or name
    # Place the worktree where production resolves it (out-of-repo since
    # story-024). worktree_path reads the SMM_DIR the _IntegrationTestCase
    # setUp pins, so create and the cleanup subprocess agree on the location.
    wt = worktree.worktree_path(name, str(tmpdir))
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)

    subprocess.run(
        ["git", "worktree", "add", "-b", branch, wt_path, "HEAD"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )

    (Path(wt_path) / f"{name}.txt").write_text(f"work by {name}")
    subprocess.run(
        ["git", "add", f"{name}.txt"],
        cwd=wt_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"Work by {name}"],
        cwd=wt_path,
        capture_output=True,
        check=True,
    )
    return wt_path


def _set_stage_2(smm_dir: Path) -> None:
    """Write system_context.json recording branching stage 2 (sprints active)."""
    (smm_dir / "system_context.json").write_text(
        json.dumps({"branching_strategy": {"stage": 2}})
    )


def _write_sprint_with_branch(smm_dir: Path, branch_name: str) -> None:
    """Write a minimal sprint.json recording `branch_name` as the story base.

    Imports `seed_sprint_with_stories` lazily for the same sys.path-ordering
    reason `_create_teammate_worktree` imports `worktree` lazily above:
    `_branching_fixtures` pulls in scripts/smm modules that aren't on
    sys.path yet when this module is first loaded via `_bases`/conftest.
    """
    from _branching_fixtures import seed_sprint_with_stories

    seed_sprint_with_stories(smm_dir, [], base_branch=branch_name)
    _set_stage_2(smm_dir)
