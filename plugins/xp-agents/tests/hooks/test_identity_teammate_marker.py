#!/usr/bin/env python3
"""Central marker-guard for is_worktree_teammate's env leg (story-006).

XP_TEAMMATE_NAME is a documented leaky var: a lead that inherits it must not be
misidentified as a teammate. is_worktree_teammate now trusts the env leg only
when spawn_teammate's lifetime-scoped in-place marker is live for that name, so
every caller (session_start, kickoff/stop gates, pre_tool_write, session_end,
bash_post_tool) inherits the guard commit_handling/pre_tool_skill already roll
by hand. The cwd-prefix leg is unchanged. conftest strips SMM_DIR at import, so
the leaked cases start with no ambient marker directory.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import identity
import worktree
from conftest import _HookTestCase

_MAIN_CWD = {"cwd": "/home/user/project/src"}
_WORKTREE_CWD = {"cwd": "/home/user/project/.claude/worktrees/worktree-story-001/src"}
_TEAMMATE = "worktree-story-001"


class TestIsWorktreeTeammateMarkerGuard(_HookTestCase):
    """The env leg of is_worktree_teammate is guarded on a live in-place marker."""

    def test_leaked_env_without_marker_is_not_teammate(self):
        """AC1: XP_TEAMMATE_NAME set but no live marker (main checkout) →
        the lead is NOT misidentified as a teammate."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            self.assertFalse(
                identity.is_worktree_teammate(_MAIN_CWD, smm_dir=self.smm_dir)
            )

    def test_live_marker_is_teammate(self):
        """AC2: a live in-place marker for the current name → still a teammate."""
        worktree.write_in_place_marker(self.smm_dir, _TEAMMATE)
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            self.assertTrue(
                identity.is_worktree_teammate(_MAIN_CWD, smm_dir=self.smm_dir)
            )

    def test_worktree_cwd_unchanged(self):
        """AC3: a worktree cwd is a teammate via the cwd-prefix leg, regardless
        of env var or marker."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            self.assertTrue(
                identity.is_worktree_teammate(_WORKTREE_CWD, smm_dir=self.smm_dir)
            )

    def test_env_not_teammate_shaped_is_not_teammate(self):
        """A non-teammate env value never reaches the marker check."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "explorer-1"}, clear=False):
            self.assertFalse(
                identity.is_worktree_teammate(_MAIN_CWD, smm_dir=self.smm_dir)
            )

    def test_resolves_smm_dir_from_env_when_param_omitted(self):
        """When smm_dir is not passed, it resolves from SMM_DIR env — a live
        marker under that dir → teammate (the real in-place-teammate path)."""
        worktree.write_in_place_marker(self.smm_dir, _TEAMMATE)
        with patch.dict(
            os.environ,
            {"XP_TEAMMATE_NAME": _TEAMMATE, "SMM_DIR": str(self.smm_dir)},
            clear=False,
        ):
            self.assertTrue(identity.is_worktree_teammate(_MAIN_CWD))

    def test_teammate_env_no_resolvable_smm_dir_is_not_teammate(self):
        """Teammate-shaped env but no smm_dir param and no SMM_DIR env → cannot
        verify a marker → not a teammate (conservative)."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            self.assertFalse(identity.is_worktree_teammate(_MAIN_CWD))

    def test_worktree_teammate_null_cwd_detected_via_process_cwd(self):
        """A WORKTREE teammate whose hook payload carries no cwd is still a
        teammate: its hook process runs IN the worktree, so os.getcwd() carries
        the worktree marker even when input_data['cwd'] is absent/null. Worktree
        spawns never write the in-place marker, so the marker-guarded env leg
        cannot rescue them — the cwd leg must consult the process cwd."""
        wt_cwd = "/home/user/project/.claude/worktrees/worktree-story-001/src"
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch("identity._process_cwd", return_value=wt_cwd):
                self.assertTrue(
                    identity.is_worktree_teammate({"cwd": None}, smm_dir=self.smm_dir)
                )

    def test_leaked_env_lead_with_main_process_cwd_is_not_teammate(self):
        """The os.getcwd() fallback must not misfire for a lead: a leaked env
        with a main-checkout process cwd and no live marker is still NOT a
        teammate (does not reintroduce leaked-env misidentification)."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch("identity._process_cwd", return_value="/home/user/project/src"):
                self.assertFalse(
                    identity.is_worktree_teammate({"cwd": None}, smm_dir=self.smm_dir)
                )

    def test_ambient_worktree_cwd_does_not_leak_into_detection(self):
        """Regression (concern 464de40cd905): lefthook runs pytest from inside a
        teammate worktree, so os.getcwd() returns the worktree path. The test
        harness must neutralize that ambient leak (conftest pins _process_cwd) so
        an unrelated test with synthetic input does not misdetect as a teammate.
        Without an explicit input_data['cwd'], detection must stay False even when
        the real os.getcwd() reports a worktree path."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            os.environ.pop("SMM_DIR", None)
            with patch(
                "identity.os.getcwd",
                return_value="/home/user/project/.claude/worktrees/worktree-story-9/src",
            ):
                self.assertFalse(identity.is_worktree_teammate({}))


if __name__ == "__main__":
    unittest.main()
