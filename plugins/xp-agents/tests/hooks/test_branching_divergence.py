#!/usr/bin/env python3
"""Tests for branching.check_plan_divergence.

Verifies plan-branch divergence detection: threshold logic, warning
generation, and merge-not-rebase suggestion.

Split from test_branching_plan.py to stay under file-size budget.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_write_system_context = _bf.write_system_context
_seed_plan = _bf.seed_plan

_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")


def _make_commit(td: str, filename: str) -> None:
    (Path(td) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )


def _run(args: list[str], smm_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _SCRIPT, "--smm-dir", str(smm_dir), *args],
        capture_output=True,
        text=True,
    )


class TestPlanDivergence(unittest.TestCase):
    """check_plan_divergence counts how far a plan branch is behind primary."""

    def _setup_diverged(self, td, smm_dir, commits_behind):
        """Create a plan branch, then advance primary by N commits."""
        _init_repo(td)
        _write_system_context(smm_dir, stage=2)

        subprocess.run(
            ["git", "checkout", "-b", "test/plan-feat"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        _make_commit(td, "plan-work.txt")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        _seed_plan(smm_dir, branch="test/plan-feat")

        for i in range(commits_behind):
            _make_commit(td, f"primary-{i}.txt")

    def test_no_plan_branch_returns_none(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            result = branching.check_plan_divergence(td, smm_dir)
            self.assertIsNone(result)

    def test_below_threshold_no_warning(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=5)

            result = branching.check_plan_divergence(td, smm_dir, threshold=10)
            self.assertIsNotNone(result)
            self.assertEqual(result["commits_behind"], 5)
            self.assertNotIn("warning", result)
            self.assertNotIn("suggestion", result)

    def test_at_threshold_has_warning(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=10)

            result = branching.check_plan_divergence(td, smm_dir, threshold=10)
            self.assertIn("warning", result)
            self.assertIn("suggestion", result)
            self.assertEqual(result["commits_behind"], 10)

    def test_above_threshold_has_warning(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=15)

            result = branching.check_plan_divergence(td, smm_dir, threshold=10)
            self.assertIn("warning", result)
            self.assertEqual(result["commits_behind"], 15)

    def test_custom_threshold(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=5)

            result = branching.check_plan_divergence(td, smm_dir, threshold=5)
            self.assertIn("warning", result)
            self.assertEqual(result["commits_behind"], 5)

    def test_suggestion_says_merge_not_rebase(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=10)

            result = branching.check_plan_divergence(td, smm_dir, threshold=10)
            self.assertIn("merge", result["suggestion"].lower())
            self.assertNotIn("rebase", result["suggestion"].lower())

    def test_check_divergence_cli_with_warning(self):
        """CLI emits JSON with warning when divergence exceeds threshold."""
        import json

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, commits_behind=10)

            r = _run(["check-divergence", "--cwd", td, "--threshold", "10"], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertIn("warning", data)
            self.assertEqual(data["commits_behind"], 10)

    def test_check_divergence_cli_no_plan(self):
        """CLI prints fallback message when no plan branch exists."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)

            r = _run(["check-divergence", "--cwd", td], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "No plan branch found")


if __name__ == "__main__":
    unittest.main()
