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
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import identity
import worktree
from _in_place_helpers import release_in_place_holds
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
        worktree.claim_in_place_marker(self.smm_dir, _TEAMMATE)
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
        worktree.claim_in_place_marker(self.smm_dir, _TEAMMATE)
        with patch.dict(
            os.environ,
            {"XP_TEAMMATE_NAME": _TEAMMATE, "SMM_DIR": str(self.smm_dir)},
            clear=False,
        ):
            self.assertTrue(identity.is_worktree_teammate(_MAIN_CWD))

    def test_env_smm_dir_follows_a_relocation_pointer(self):
        """The pinned handle addresses ONE tree, before and after a relocation.

        SMM_DIR is pinned at spawn and the SMM can move under it. Every other
        reader follows the forward pointer the relocation leaves behind, so this
        marker lookup must too: reading the abandoned tree would keep answering
        from a marker copy nobody clears, long after the teammate exited.
        """
        moved = Path(self.enterContext(tempfile.TemporaryDirectory()))
        worktree.claim_in_place_marker(moved, _TEAMMATE)
        self.addCleanup(release_in_place_holds, moved)
        (self.smm_dir / ".migrated-to").write_text(f"{moved}\n")
        with patch.dict(
            os.environ,
            {"XP_TEAMMATE_NAME": _TEAMMATE, "SMM_DIR": str(self.smm_dir)},
            clear=False,
        ):
            self.assertTrue(identity.is_worktree_teammate(_MAIN_CWD))

    def test_teammate_env_no_resolvable_smm_dir_is_not_teammate(self):
        """AC3 (story-003): teammate-shaped env but no way to locate the marker
        (no param, no SMM_DIR env) → cannot verify a marker → not a teammate
        (fails closed WITHOUT deriving the shared SMM)."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "resolve_smm_dir") as mock_resolve:
                self.assertFalse(identity.is_worktree_teammate(_MAIN_CWD))
            mock_resolve.assert_not_called()

    def test_leaked_env_no_param_no_env_does_not_derive_shared_smm(self):
        """Finding #6 / story-003 fail-closed: with no smm_dir param and no
        SMM_DIR env, is_worktree_teammate must NOT derive the real shared SMM
        via init.sh — a live in-place marker there for a LEAKED name would
        misidentify the lead as a teammate. Even with a live marker present in
        the (would-be-derived) shared SMM, it returns False WITHOUT resolving."""
        worktree.claim_in_place_marker(self.smm_dir, _TEAMMATE)
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _TEAMMATE}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "resolve_smm_dir") as mock_resolve:
                self.assertFalse(identity.is_worktree_teammate(_MAIN_CWD))
            mock_resolve.assert_not_called()

    def test_no_env_var_never_resolves_smm_dir(self):
        """AC4 (story-003): with no XP_TEAMMATE_NAME, the lead's hot path pays
        no subprocess — pinned via call count, not vacuously."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            with patch.object(_common, "resolve_smm_dir") as mock_resolve:
                self.assertFalse(identity.is_worktree_teammate(_MAIN_CWD))
            mock_resolve.assert_not_called()

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
        """Guards the conftest harness pin (concern 464de40cd905). lefthook runs
        pytest from inside a teammate worktree, where os.getcwd() reports the
        worktree path; conftest pins identity._process_cwd to '' so that ambient
        value never reaches is_worktree_teammate. This asserts the pin dominates:
        even with os.getcwd patched to a worktree path, a synthetic input with no
        'cwd' stays False. If the pin were removed, _process_cwd would read the
        patched os.getcwd and this would flip to True — so the test fails loud."""
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
