#!/usr/bin/env python3
"""Tests for worktree.py marker helpers — story assignment path and
in-place teammate env lookup.

Covers: story_assignment_path, in_place_teammate_from_env.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree


class TestStoryAssignmentPath(unittest.TestCase):
    def test_returns_dotfile_in_smm_dir(self):
        """story_assignment_path returns {smm_dir}/.story-assignment-{name}."""
        result = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        self.assertEqual(result, Path("/smm/.story-assignment-teammate-step-1"))

    def test_different_names_produce_different_paths(self):
        result_a = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        result_b = worktree.story_assignment_path(Path("/smm"), "teammate-step-2")
        self.assertNotEqual(result_a, result_b)


class TestInPlaceTeammateFromEnv(unittest.TestCase):
    """in_place_teammate_from_env returns True when env_name names a live
    in-place teammate (marker present), False otherwise.

    Wraps the env-name-not-None + in_place_marker_exists check that
    identity, pre_tool_skill, and commit_handling previously rolled by hand.
    Caller-side id-shape validation (is_teammate_agent_id) and smm_dir
    resolution stay at call sites; the helper centralizes the core guard.
    """

    def test_returns_true_when_marker_present_and_env_not_none(self):
        """When env_name is non-None and marker exists, returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            worktree.write_in_place_marker(smm_dir, "worktree-story-001")
            result = worktree.in_place_teammate_from_env(smm_dir, "worktree-story-001")
            self.assertTrue(result)

    def test_returns_false_when_env_name_is_none(self):
        """When env_name is None, returns False (no marker lookup)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            result = worktree.in_place_teammate_from_env(smm_dir, None)
            self.assertFalse(result)

    def test_returns_false_when_marker_absent(self):
        """When env_name is non-None but marker doesn't exist, returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            result = worktree.in_place_teammate_from_env(smm_dir, "worktree-story-999")
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
