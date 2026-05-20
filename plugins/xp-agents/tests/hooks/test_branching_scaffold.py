#!/usr/bin/env python3
"""Tests for branching.create_scaffold_branch — scaffold-branch creation/resume.

The scaffold branch helper is the only create_*_branch path that pairs with
``commit_scaffold``'s structured ``CommitResult(ok=False, reason=...)`` error
contract (per scaffolding-doctrine §Commit Strategy). When ``git checkout``
fails on a dirty-resume conflict, this helper must surface the failure as
``None`` so callers can wrap it in ``CommitResult(ok=False, reason=...)`` —
not ``sys.exit(1)``, which short-circuits the caller's structured-error path.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching

_init_repo = _bf.init_repo
_write_system_context = _bf.write_system_context
_make_commit = _bf.make_commit
GIT_ENV = _bf.GIT_ENV


def _commits_on(cwd: str, branch: str) -> set[str]:
    """Full set of commit SHAs reachable from ``branch``."""
    out = subprocess.run(
        ["git", "log", "--format=%H", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {line for line in out.splitlines() if line}


class TestCreateScaffoldBranch(unittest.TestCase):
    def test_creates_branch_at_stage_one(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertEqual(result, "paul/scaffold-browser")

    def test_skips_at_stage_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_scaffold_branch(td, "browser", Path(smm))
            self.assertIsNone(result)

    def test_returns_none_on_dirty_resume_conflict(self) -> None:
        """Resume path: scaffold branch exists; uncommitted changes that
        ``git checkout`` would clobber. Must return ``None`` (so commit_scaffold
        can map to ``CommitResult(ok=False, reason=...)``), not sys.exit."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            _make_commit(
                td,
                "paul/scaffold-browser",
                "marker.txt",
                "scaffold-version\n",
                "scaffold marker",
            )
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=td,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )
            (Path(td) / "marker.txt").write_text("conflicting-untracked\n")

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertIsNone(result)

    def test_forks_off_current_sprint_branch(self) -> None:
        """Non-protected current (sprint) → scaffold forks off it, not primary."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            sentinel = _make_commit(
                td, "paul/sprint-088-x", "s.txt", "sprint\n", "sprint work"
            )

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertEqual(result, "paul/scaffold-browser")
            self.assertIn(sentinel, _commits_on(td, "paul/scaffold-browser"))

    def test_forks_off_current_free_branch(self) -> None:
        """Non-protected current (free) → scaffold forks off it."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            sentinel = _make_commit(
                td, "paul/free-2026-05-20-x", "f.txt", "free\n", "free work"
            )

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertEqual(result, "paul/scaffold-browser")
            self.assertIn(sentinel, _commits_on(td, "paul/scaffold-browser"))

    def test_protected_non_primary_forks_off_current_not_primary(self) -> None:
        """Stage 3: on main (protected, NOT primary) → scaffold forks off main,
        not the integration_branch primary. Pins base = current always, even
        for a protected base — the old code forked off primary here."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=3, integration_branch="develop")
            dev_sentinel = _make_commit(td, "develop", "d.txt", "dev\n", "dev work")
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=td,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )
            _bf.append_commit(td, "m.txt")
            main_sentinel = _bf.get_head_sha(td)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertEqual(result, "paul/scaffold-browser")
            reachable = _commits_on(td, "paul/scaffold-browser")
            self.assertIn(main_sentinel, reachable)
            self.assertNotIn(dev_sentinel, reachable)

    def test_refuses_on_story_branch(self) -> None:
        """Story branch current → guard returns None and creates no branch,
        so a scaffold never enters a story's file_domain."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _make_commit(td, "paul/story-007-x", "x.txt", "story\n", "story work")

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_scaffold_branch(td, "browser", smm_dir)

            self.assertIsNone(result)
            self.assertFalse(_bf.branch_exists(td, "paul/scaffold-browser"))


if __name__ == "__main__":
    unittest.main()
