#!/usr/bin/env python3
"""Tests for identity.py — WHICH AGENT AM I.

Covers resolve_agent_id, is_teammate_agent_id, in_place_teammate_name and
is_worktree_teammate: the inference from cwd and env that decides whether a
process is the lead or a teammate, and which teammate. Split at 582 lines —
user_namespace moved to test_identity_namespace.py and the branch readers to
test_identity_branch.py.
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

# Direct from the sibling, NOT through conftest: this module deliberately does
# not import conftest (see TestIsWorktreeTeammate.setUp — it must stand alone
# under an isolated `python3 -m unittest hooks.test_identity`).
from _in_place_helpers import release_in_place_holds


class TestResolveAgentId(unittest.TestCase):
    def test_platform_provided_agent_id(self):
        result = identity.resolve_agent_id({"agent_id": "xp-teammate-001"})
        self.assertEqual(result, "xp-teammate-001")

    def test_worktree_cwd_extracts_name(self):
        result = identity.resolve_agent_id(
            {"cwd": "/home/user/project/.claude/worktrees/worktree-story-001"}
        )
        self.assertEqual(result, "worktree-story-001")

    def test_nested_worktree_cwd(self):
        result = identity.resolve_agent_id(
            {"cwd": "/home/user/project/.claude/worktrees/worktree-story-001/src/lib"}
        )
        self.assertEqual(result, "worktree-story-001")

    def test_out_of_repo_worktree_cwd_extracts_name(self):
        """Detection keys on the `worktree-story-` SEGMENT, so it still fires
        at the new out-of-repo placement (`{project-id}/worktrees/...`) — no
        `.claude/worktrees/` parent required (story-024)."""
        result = identity.resolve_agent_id(
            {"cwd": "/data/plugin/proj-abc/worktrees/worktree-story-001/src"}
        )
        self.assertEqual(result, "worktree-story-001")

    def test_non_worktree_cwd_returns_main(self):
        result = identity.resolve_agent_id({"cwd": "/home/user/project/src"})
        self.assertEqual(result, "main")

    def test_no_cwd_returns_main(self):
        result = identity.resolve_agent_id({})
        self.assertEqual(result, "main")

    def test_empty_agent_id_falls_through_to_cwd(self):
        result = identity.resolve_agent_id(
            {"agent_id": "", "cwd": "/x/.claude/worktrees/worktree-story-002"}
        )
        self.assertEqual(result, "worktree-story-002")

    def test_platform_agent_id_takes_precedence_over_worktree_cwd(self):
        inp = {
            "agent_id": "subagent-abc",
            "cwd": "/x/.claude/worktrees/worktree-story-001",
        }
        result = identity.resolve_agent_id(inp)
        self.assertEqual(result, "subagent-abc")


class TestIsTeammateAgentId(unittest.TestCase):
    """is_teammate_agent_id detects worktree-story-* agent IDs."""

    def test_worktree_story_detected(self):
        self.assertTrue(identity.is_teammate_agent_id("worktree-story-001"))

    def test_old_teammate_prefix_not_detected(self):
        self.assertFalse(identity.is_teammate_agent_id("teammate-step-1"))

    def test_main_not_detected(self):
        self.assertFalse(identity.is_teammate_agent_id("main"))

    def test_xp_agent_not_detected(self):
        self.assertFalse(identity.is_teammate_agent_id("xp-kickoff"))

    def test_empty_string_not_detected(self):
        self.assertFalse(identity.is_teammate_agent_id(""))


class TestInPlaceTeammateName(unittest.TestCase):
    """in_place_teammate_name — the shared marker-guarded env leg behind
    is_worktree_teammate, tdd_check._reader_scope, and
    pre_tool_skill._is_live_teammate (story-003 dedup)."""

    def test_no_env_var_never_resolves_smm_dir(self):
        """AC4: with no XP_TEAMMATE_NAME, the lead's hot path pays no
        subprocess — pinned via call count, not vacuously."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            with patch.object(_common, "get_validated_smm_dir") as mock_resolve:
                self.assertIsNone(identity.in_place_teammate_name())
            mock_resolve.assert_not_called()

    def test_env_var_not_teammate_shaped_never_resolves_smm_dir(self):
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "explorer-1"}, clear=False):
            with patch.object(_common, "get_validated_smm_dir") as mock_resolve:
                self.assertIsNone(identity.in_place_teammate_name())
            mock_resolve.assert_not_called()

    def test_invalid_explicit_smm_dir_fails_closed(self):
        """An explicit smm_dir that fails validation must never reach
        in_place_teammate_from_env."""
        with (
            patch.dict(
                os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
            ),
            patch.object(_common, "try_validate_smm_dir", return_value=None),
        ):
            with patch("worktree.in_place_teammate_from_env") as mock_marker:
                self.assertIsNone(identity.in_place_teammate_name(Path("/whatever")))
            mock_marker.assert_not_called()

    def test_no_param_and_no_env_fails_closed_without_deriving(self):
        """Finding #6 / story-003 fail-closed: with neither an smm_dir param
        nor a SMM_DIR env, the marker is unverifiable. The helper must NOT
        derive the real shared SMM via init.sh — that would let a live in-place
        marker for a LEAKED XP_TEAMMATE_NAME misidentify a lead as a teammate.
        It returns None WITHOUT ever resolving or checking the marker."""
        with patch.dict(
            os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
        ):
            os.environ.pop("SMM_DIR", None)
            with (
                patch.object(_common, "resolve_smm_dir") as mock_resolve,
                patch("worktree.in_place_teammate_from_env") as mock_marker,
            ):
                self.assertIsNone(identity.in_place_teammate_name())
            mock_resolve.assert_not_called()
            mock_marker.assert_not_called()

    def test_leaked_env_without_live_marker_returns_none(self):
        """A leaked XP_TEAMMATE_NAME with a resolvable SMM but NO live marker
        is not a teammate — the marker is checkABLE, never skippable."""
        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = Path(tmp)
            with patch.dict(
                os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
            ):
                self.assertIsNone(identity.in_place_teammate_name(smm_dir))

    def test_process_cwd_inside_a_worktree_is_ignored(self):
        """The helper is the ENV leg and nothing else — it must carry no cwd
        logic of its own. `is_worktree_teammate` keeps its `os.getcwd()`
        fallback ABOVE the call; `tdd_check._reader_scope` and
        `pre_tool_skill._is_live_teammate` deliberately have none (that leak is
        the documented reason they don't just call `is_worktree_teammate`).
        That separation only holds while this helper stays cwd-free, so pin it
        here: a process cwd inside a worktree, with no env var, is still None."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            with patch(
                "identity._process_cwd",
                return_value="/tmp/wt/worktree-story-001",
            ):
                self.assertIsNone(identity.in_place_teammate_name())

    def test_explicit_smm_dir_param_used_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = Path(tmp)
            worktree.claim_in_place_marker(smm_dir, "worktree-story-001")
            try:
                with patch.dict(
                    os.environ,
                    {"XP_TEAMMATE_NAME": "worktree-story-001"},
                    clear=False,
                ):
                    self.assertEqual(
                        identity.in_place_teammate_name(smm_dir),
                        "worktree-story-001",
                    )
            finally:
                release_in_place_holds(smm_dir)


class TestIsWorktreeTeammate(unittest.TestCase):
    """is_worktree_teammate detects CLI teammates by cwd path or env var."""

    def setUp(self):
        # Neutralize the ambient process-cwd fallback so these assertions hold
        # regardless of where the suite runs from (concern 464de40cd905). The
        # conftest module-level pin covers full-suite runs, but this module does
        # not import conftest, so an isolated `python3 -m unittest hooks.test_identity`
        # launched from inside a teammate worktree would otherwise see os.getcwd()
        # leak a worktree marker and flip every no-worktree-cwd case to True.
        patcher = patch("identity._process_cwd", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_worktree_story_cwd_detected(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/worktree-story-001/src"}
        self.assertTrue(identity.is_worktree_teammate(inp))

    def test_worktree_story_cwd_root(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/worktree-story-002"}
        self.assertTrue(identity.is_worktree_teammate(inp))

    def test_out_of_repo_worktree_detected(self):
        """A teammate at the new out-of-repo placement (sibling of the SMM
        dir) is still detected — the load-bearing spike-014 interface
        contract (story-024)."""
        inp = {"cwd": "/data/plugin/proj-abc/worktrees/worktree-story-001/src"}
        self.assertTrue(identity.is_worktree_teammate(inp))

    def test_old_teammate_worktree_not_detected(self):
        """Old teammate-* cwd pattern is no longer detected."""
        inp = {"cwd": "/home/user/project/.claude/worktrees/teammate-old/src"}
        self.assertFalse(identity.is_worktree_teammate(inp))

    def test_non_teammate_worktree_not_detected(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/explore-abc/src"}
        self.assertFalse(identity.is_worktree_teammate(inp))

    def test_regular_cwd_not_detected(self):
        inp = {"cwd": "/home/user/project/src"}
        self.assertFalse(identity.is_worktree_teammate(inp))

    def test_empty_cwd_not_detected(self):
        self.assertFalse(identity.is_worktree_teammate({"cwd": ""}))

    def test_no_cwd_field_not_detected(self):
        self.assertFalse(identity.is_worktree_teammate({}))

    def test_env_var_fallback_requires_live_marker(self):
        """XP_TEAMMATE_NAME (main-checkout cwd) detects a teammate only with a
        live in-place marker; a leaked env with no marker is not a teammate
        (story-006 central guard)."""
        import worktree

        inp = {"cwd": "/home/user/project/src"}
        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = Path(tmp)
            with patch.dict(
                os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
            ):
                os.environ.pop("SMM_DIR", None)
                self.assertFalse(identity.is_worktree_teammate(inp, smm_dir=smm_dir))
                worktree.claim_in_place_marker(smm_dir, "worktree-story-001")
                detected = identity.is_worktree_teammate(inp, smm_dir=smm_dir)
                # The claim holds a REAL lock; give it back before the dir goes.
                release_in_place_holds(smm_dir)
                self.assertTrue(detected)

    def test_leaked_env_no_smm_dir_does_not_derive_shared_smm(self):
        """Finding #6: a lead with a leaked XP_TEAMMATE_NAME and no SMM_DIR must
        NOT be misidentified as a teammate by deriving the real shared SMM and
        finding a live in-place marker there. With neither an smm_dir param nor
        a SMM_DIR env, the env leg fails closed WITHOUT deriving (story-003's
        fail-closed property)."""
        inp = {"cwd": "/home/user/project/src"}
        with patch.dict(
            os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
        ):
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "resolve_smm_dir") as mock_resolve:
                self.assertFalse(identity.is_worktree_teammate(inp))
            mock_resolve.assert_not_called()

    def test_env_var_without_prefix_not_detected(self):
        """XP_TEAMMATE_NAME without worktree-story- prefix not detected."""
        inp = {"cwd": "/home/user/project/src"}
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "explorer-1"}):
            self.assertFalse(identity.is_worktree_teammate(inp))

    def test_cwd_takes_precedence_over_env_var(self):
        """CWD detection still works even when env var is set."""
        inp = {"cwd": "/home/user/project/.claude/worktrees/worktree-story-001"}
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-002"}):
            self.assertTrue(identity.is_worktree_teammate(inp))


if __name__ == "__main__":
    unittest.main()
