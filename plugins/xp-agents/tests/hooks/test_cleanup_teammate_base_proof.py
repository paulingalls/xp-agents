#!/usr/bin/env python3
"""Tests for cleanup_teammate.py proving merges against the story base.

Split from test_cleanup_teammate.py (feature split, per the max-500 rule):
covers verify_merged/main() proving against the recorded story base branch
rather than HEAD, and failing closed when that base is unresolvable.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, cleanup_test_worktrees


def _create_teammate_worktree(
    tmpdir: Path, name: str, branch: str | None = None
) -> str:
    """Create a worktree with a commit. Returns worktree path."""
    branch = branch or name
    wt_dir = tmpdir / ".claude" / "worktrees"
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt_dir / name)

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
    """Write a minimal sprint.json recording `branch_name` as the story base."""
    sprint = {
        "sprint_id": "sprint-1",
        "goal": "test sprint",
        "started": "2026-01-01T00:00:00Z",
        "branch_name": branch_name,
        "stories": [],
    }
    (smm_dir / "sprint.json").write_text(json.dumps(sprint))
    _set_stage_2(smm_dir)


class TestVerifyMergedAgainstBase(_IntegrationTestCase):
    """verify_merged proves against the given base, independent of HEAD."""

    def test_verify_merged_proves_against_base_arg(self):
        """Proves ancestry against the given base, independent of HEAD.

        A branch merged into `storybase` but not into the currently
        checked-out `main` must read as merged when `base=storybase`, and
        an unmerged sibling must read as unmerged against the same base.
        """
        import cleanup_teammate

        subprocess.run(
            ["git", "branch", "storybase-001"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        merged_name = "worktree-story-090"
        _create_teammate_worktree(self.tmpdir, merged_name)
        subprocess.run(
            ["git", "checkout", "storybase-001"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "merge", merged_name, "--no-ff", "-m", f"Merge {merged_name}"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        unmerged_name = "worktree-story-091"
        _create_teammate_worktree(self.tmpdir, unmerged_name)

        self.assertTrue(
            cleanup_teammate.verify_merged(
                merged_name, str(self.tmpdir), "storybase-001"
            ),
            "Merged into base (not HEAD) must read as merged",
        )
        self.assertFalse(
            cleanup_teammate.verify_merged(
                unmerged_name, str(self.tmpdir), "storybase-001"
            ),
            "Unmerged into base must read as unmerged",
        )

    def tearDown(self):
        subprocess.run(
            ["git", "branch", "-D", "storybase-001"],
            cwd=self.tmpdir,
            capture_output=True,
        )
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


class TestMainProvesAgainstStoryBase(_IntegrationTestCase):
    """main() resolves the recorded story base and proves the merge against it.

    Covers the concern this story fixes: a branch merged into its recorded
    story base but not into the current HEAD must not be misjudged as
    unmerged, and an unresolvable base must fail closed rather than delete
    on an unknowable merge state.
    """

    def test_cleanup_deletes_branch_merged_to_base_not_head(self):
        """Branch merged to the recorded story base, but HEAD advanced past it.

        `main` derives the branch from the worktree, resolves the recorded
        story base, and proves the merge against that base rather than HEAD.
        """
        import cleanup_teammate

        subprocess.run(
            ["git", "branch", "storybase-092"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        wt_name = "worktree-story-092"
        branch = "paulingalls/story-092-base-merged"
        _create_teammate_worktree(self.tmpdir, wt_name, branch=branch)

        subprocess.run(
            ["git", "checkout", "storybase-092"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "merge", branch, "--no-ff", "-m", f"Merge {branch}"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        (self.tmpdir / "unrelated.txt").write_text("advance HEAD past the base")
        subprocess.run(
            ["git", "add", "unrelated.txt"], cwd=self.tmpdir, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Advance main past storybase-092"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        _write_sprint_with_branch(self.smm_dir, "storybase-092")

        rc = cleanup_teammate.main(
            [
                "--name",
                wt_name,
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ]
        )

        self.assertEqual(rc, 0, "Merged-to-base branch should be cleaned up")
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "", "Branch should be deleted")

        subprocess.run(
            ["git", "branch", "-D", "storybase-092"],
            cwd=self.tmpdir,
            capture_output=True,
        )

    def test_cleanup_refuses_branch_unmerged_into_base(self):
        """Branch not merged into the recorded story base is refused, not dropped."""
        import cleanup_teammate

        subprocess.run(
            ["git", "branch", "storybase-093"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        wt_name = "worktree-story-093"
        branch = "paulingalls/story-093-base-unmerged"
        wt_path = _create_teammate_worktree(self.tmpdir, wt_name, branch=branch)
        # Do NOT merge into storybase-093 or main.

        _write_sprint_with_branch(self.smm_dir, "storybase-093")

        rc = cleanup_teammate.main(
            [
                "--name",
                wt_name,
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ]
        )

        self.assertEqual(rc, 1, "Unmerged-into-base branch must be refused")
        self.assertTrue(Path(wt_path).is_dir(), "Worktree dir must be kept")
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertIn(branch, result.stdout, "Branch must be kept")

        subprocess.run(
            ["git", "branch", "-D", "storybase-093"],
            cwd=self.tmpdir,
            capture_output=True,
        )

    def test_cleanup_fails_closed_on_unresolvable_base(self):
        """Corrupt/unresolvable story base fails closed — nothing is deleted."""
        import cleanup_teammate

        wt_name = "worktree-story-094"
        branch = "paulingalls/story-094-unresolvable-base"
        wt_path = _create_teammate_worktree(self.tmpdir, wt_name, branch=branch)
        subprocess.run(
            ["git", "merge", branch, "--no-ff", "-m", f"Merge {branch}"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        _write_sprint_with_branch(self.smm_dir, "branch-that-does-not-exist")

        rc = cleanup_teammate.main(
            [
                "--name",
                wt_name,
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ]
        )

        self.assertEqual(rc, 1, "Unresolvable base must fail closed")
        self.assertTrue(Path(wt_path).is_dir(), "Worktree dir must be kept")
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertIn(branch, result.stdout, "Branch must be kept")

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
