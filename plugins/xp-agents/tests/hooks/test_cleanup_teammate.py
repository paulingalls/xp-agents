#!/usr/bin/env python3
"""Tests for cleanup_teammate.py — teammate worktree cleanup.

Covers: verify_merged, cleanup (worktree, branch, markers, report),
error cases (unmerged branch, missing worktree, missing report).
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, cleanup_test_worktrees


def _create_teammate_worktree(tmpdir: Path, name: str) -> str:
    """Create a teammate worktree with a commit. Returns worktree path."""
    wt_dir = tmpdir / ".claude" / "worktrees"
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt_dir / name)

    subprocess.run(
        ["git", "worktree", "add", "-b", name, wt_path, "HEAD"],
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


def _merge_branch(tmpdir: Path, name: str) -> None:
    """Merge a teammate branch into the current branch."""
    subprocess.run(
        ["git", "merge", name, "--no-ff", "-m", f"Merge {name}"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )


class TestVerifyMerged(_IntegrationTestCase):
    """verify_merged checks if a branch is fully merged."""

    def test_returns_true_when_merged(self):
        """Branch merged into current branch returns True."""
        import cleanup_teammate

        name = "teammate-story-001"
        _create_teammate_worktree(self.tmpdir, name)
        _merge_branch(self.tmpdir, name)

        self.assertTrue(cleanup_teammate.verify_merged(name, str(self.tmpdir)))

    def test_returns_false_when_not_merged(self):
        """Branch with unmerged commits returns False."""
        import cleanup_teammate

        name = "teammate-story-002"
        _create_teammate_worktree(self.tmpdir, name)

        self.assertFalse(cleanup_teammate.verify_merged(name, str(self.tmpdir)))

    def test_returns_false_for_nonexistent_branch(self):
        """Non-existent branch returns False."""
        import cleanup_teammate

        self.assertFalse(
            cleanup_teammate.verify_merged("teammate-ghost", str(self.tmpdir))
        )

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


class TestCleanup(_IntegrationTestCase):
    """cleanup removes worktree, branch, markers, and report file."""

    def test_removes_merged_worktree_and_branch(self):
        """After merge, cleanup removes the worktree dir and branch."""
        import cleanup_teammate

        name = "teammate-story-010"
        wt_path = _create_teammate_worktree(self.tmpdir, name)
        _merge_branch(self.tmpdir, name)

        cleanup_teammate.cleanup(name, str(self.tmpdir), self.smm_dir)

        self.assertFalse(
            Path(wt_path).is_dir(),
            "Worktree dir should be removed",
        )
        result = subprocess.run(
            ["git", "branch", "--list", name],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.strip(),
            "",
            "Branch should be deleted",
        )

    def test_removes_agent_markers(self):
        """Cleanup removes agent-scoped marker files."""
        import cleanup_teammate
        import markers

        name = "teammate-story-011"
        _create_teammate_worktree(self.tmpdir, name)
        _merge_branch(self.tmpdir, name)

        # Create agent-scoped markers
        markers.write_review_cycle(self.smm_dir, name, {"simplify_done": True})
        tdd_path = markers.marker_path(self.smm_dir, markers.TDD_TRACKER, name)
        markers.marker_write(
            self.smm_dir,
            markers.TDD_TRACKER,
            {"test_file": "test.py"},
            name,
        )
        self.assertTrue(tdd_path.exists())

        cleanup_teammate.cleanup(name, str(self.tmpdir), self.smm_dir)

        rc_path = markers.marker_path(self.smm_dir, markers.REVIEW_CYCLE, name)
        self.assertFalse(rc_path.exists(), "Review cycle marker gone")
        self.assertFalse(tdd_path.exists(), "TDD tracker marker gone")

    def test_removes_report_file(self):
        """Cleanup removes .teammate-report-{name}.txt."""
        import cleanup_teammate

        name = "teammate-story-012"
        _create_teammate_worktree(self.tmpdir, name)
        _merge_branch(self.tmpdir, name)

        report = self.smm_dir / f".teammate-report-{name}.txt"
        report.write_text("Teammate report content")
        self.assertTrue(report.exists())

        cleanup_teammate.cleanup(name, str(self.tmpdir), self.smm_dir)

        self.assertFalse(report.exists(), "Report file should be removed")

    def test_handles_missing_worktree(self):
        """No error when worktree is already gone."""
        import cleanup_teammate

        name = "teammate-story-013"
        # Create branch but no worktree dir
        subprocess.run(
            ["git", "branch", name],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        report = self.smm_dir / f".teammate-report-{name}.txt"
        report.write_text("leftover report")

        # Should not raise — cleans up what it can
        cleanup_teammate.cleanup(name, str(self.tmpdir), self.smm_dir)

        self.assertFalse(report.exists())

    def test_handles_missing_report(self):
        """No error when report file doesn't exist."""
        import cleanup_teammate

        name = "teammate-story-014"
        _create_teammate_worktree(self.tmpdir, name)
        _merge_branch(self.tmpdir, name)

        cleanup_teammate.cleanup(name, str(self.tmpdir), self.smm_dir)

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
