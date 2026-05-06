#!/usr/bin/env python3
"""Capstone: full free-session branch lifecycle end-to-end.

Wires the seams of stories 001 + 002 (M-4 Pass 2) on a hermetic repo
without mocks: auto-create on protected → commits on the free branch
→ next-kickoff orphan-detection → close + merge into primary →
branch deleted. Asserts the cross-cutting invariants per
execution_plan.json M-4 done-state.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching
from _branching_fixtures import (
    GIT_ENV,
    get_current_branch,
    get_head_sha,
    write_system_context,
)
from conftest import _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_KICKOFF_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"
)


def _commit_file(cwd: str, filename: str, content: str, message: str) -> str:
    """Write filename+content on the current branch, commit, return SHA."""
    (Path(cwd) / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=cwd, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd,
        capture_output=True,
        check=True,
        env=GIT_ENV,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestFreeSessionLifecycle(_IntegrationTestCase):
    """Stage 1: free-branch auto-create → commit → orphan → merge → delete."""

    def setUp(self):
        super().setUp()
        write_system_context(self.smm_dir, stage=1)

    def test_full_lifecycle_end_to_end(self):
        cwd = str(self.tmpdir)
        primary = get_current_branch(cwd)
        self.assertEqual(primary, "main", "fixture must start on main")
        primary_sha_before = get_head_sha(cwd)

        # ---- Step 1: kickoff #1 — fresh, no orphans ----
        kickoff1 = self._run_preload(_KICKOFF_PRELOAD)
        self.assertEqual(kickoff1.returncode, 0, kickoff1.stderr)
        self.assertNotIn("ORPHAN_FREE_BRANCHES", kickoff1.stdout)

        # ---- Step 2: simulate Step 2.5 auto-create + 2 commits ----
        free_branch = branching.create_free_branch(cwd, "tinker", self.smm_dir)
        free_branch = self._assert_not_none(free_branch)
        self.assertEqual(get_current_branch(cwd), free_branch)

        sha1 = _commit_file(cwd, "tinker_a.txt", "alpha", "free: alpha")
        sha2 = _commit_file(cwd, "tinker_b.txt", "beta", "free: beta")
        self.assertNotEqual(sha1, sha2)

        # ---- Step 3: switch back to primary; kickoff #2 surfaces orphan ----
        subprocess.run(
            ["git", "checkout", primary],
            cwd=cwd,
            capture_output=True,
            check=True,
        )
        kickoff2 = self._run_preload(_KICKOFF_PRELOAD)
        self.assertEqual(kickoff2.returncode, 0, kickoff2.stderr)
        self.assertIn("ORPHAN_FREE_BRANCHES", kickoff2.stdout)
        self.assertIn(free_branch, kickoff2.stdout)

        # ---- Step 4: merge the orphan into primary with --no-ff ----
        branching.merge_branch(cwd, free_branch, target=primary)
        self.assertEqual(get_current_branch(cwd), primary)

        primary_sha_after = get_head_sha(cwd)
        self.assertNotEqual(primary_sha_after, primary_sha_before)

        # --no-ff merge produces 2 parents.
        parents = (
            subprocess.run(
                ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .split()
        )
        self.assertEqual(
            len(parents), 3, f"--no-ff merge must produce 2 parents, got: {parents}"
        )
        self.assertEqual(parents[1], primary_sha_before)
        self.assertEqual(parents[2], sha2)

        # Both files from the free branch are now present on primary.
        self.assertTrue((self.tmpdir / "tinker_a.txt").exists())
        self.assertTrue((self.tmpdir / "tinker_b.txt").exists())

        # ---- Step 5: delete the merged free branch ----
        deleted = branching.delete_branch(cwd, free_branch)
        self.assertTrue(deleted)
        verify = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{free_branch}"],
            cwd=cwd,
            capture_output=True,
        )
        self.assertNotEqual(verify.returncode, 0, "branch must be gone after delete")

        # ---- Step 6: kickoff #3 sees no orphan again ----
        kickoff3 = self._run_preload(_KICKOFF_PRELOAD)
        self.assertEqual(kickoff3.returncode, 0, kickoff3.stderr)
        self.assertNotIn("ORPHAN_FREE_BRANCHES", kickoff3.stdout)


if __name__ == "__main__":
    unittest.main()
