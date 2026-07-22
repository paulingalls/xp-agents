#!/usr/bin/env python3
"""Tests for identity.py — agent identity resolution utilities.

Covers: resolve_agent_id, is_worktree_teammate, get_current_branch, user_namespace.
"""

import os
import subprocess
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
from _branching_fixtures import init_repo

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

    def test_unresolvable_smm_dir_fails_closed(self):
        """AC3: get_validated_smm_dir returning None must never reach
        in_place_teammate_from_env."""
        with (
            patch.dict(
                os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
            ),
            patch.object(_common, "get_validated_smm_dir", return_value=None),
        ):
            with patch("worktree.in_place_teammate_from_env") as mock_marker:
                self.assertIsNone(identity.in_place_teammate_name())
            mock_marker.assert_not_called()

    def test_self_resolves_dir_when_param_and_env_both_absent(self):
        """AC1: no smm_dir param, no SMM_DIR env — resolution runs through the
        same validated resolver every hook shares (mocked here to stand in for
        init.sh derivation)."""
        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = Path(tmp)
            worktree.claim_in_place_marker(smm_dir, "worktree-story-001")
            try:
                with patch.dict(
                    os.environ,
                    {"XP_TEAMMATE_NAME": "worktree-story-001"},
                    clear=False,
                ):
                    with patch.object(
                        _common, "get_validated_smm_dir", return_value=smm_dir
                    ) as mock_resolve:
                        result = identity.in_place_teammate_name()
                    mock_resolve.assert_called_once_with(None)
                self.assertEqual(result, "worktree-story-001")
            finally:
                release_in_place_holds(smm_dir)

    def test_leaked_env_without_live_marker_returns_none_even_when_resolved(self):
        """AC2: self-resolution makes the marker CHECKABLE, never SKIPPABLE."""
        with tempfile.TemporaryDirectory() as tmp:
            smm_dir = Path(tmp)
            with (
                patch.dict(
                    os.environ, {"XP_TEAMMATE_NAME": "worktree-story-001"}, clear=False
                ),
                patch.object(_common, "get_validated_smm_dir", return_value=smm_dir),
            ):
                self.assertIsNone(identity.in_place_teammate_name())

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


class TestUserNamespace(unittest.TestCase):
    """user_namespace extracts a slug from git config for branch naming."""

    def test_email_local_part_slug(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="paul@paulingalls.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_email_with_dots_and_plus(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="first.last+tag@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "first-last-tag")

    def test_uppercase_lowered(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="PAUL@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_name_fallback(self):
        email_result = subprocess.CompletedProcess([], 1, stdout="")
        name_result = subprocess.CompletedProcess([], 0, stdout="Paul Ingalls\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul-ingalls")

    def test_both_unset_returns_default(self):
        fail = subprocess.CompletedProcess([], 1, stdout="")
        with patch("identity.subprocess.run", return_value=fail):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_email_without_at_falls_to_name(self):
        """Email without @ is ignored, falls back to user.name."""
        email_result = subprocess.CompletedProcess([], 0, stdout="localonly\n")
        name_result = subprocess.CompletedProcess([], 0, stdout="Fallback Name\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "fallback-name")

    def test_slugify_all_special_chars_falls_to_default(self):
        """Email local-part that slugifies to empty falls through."""
        email_result = subprocess.CompletedProcess([], 0, stdout="---@example.com\n")
        fail = subprocess.CompletedProcess([], 1, stdout="")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return fail

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_real_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            result = identity.user_namespace(td)
            self.assertEqual(result, "test")


class TestGetCurrentBranch(unittest.TestCase):
    """get_current_branch returns branch name or empty string."""

    def test_returns_branch_in_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            result = identity.get_current_branch(td)
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_returns_empty_on_invalid_dir(self):
        result = identity.get_current_branch("/nonexistent/path")
        self.assertEqual(result, "")


class TestExtractStoryId(unittest.TestCase):
    """extract_story_id parses `<user>/story-NNN-<slug>` branch names.

    Powers /xp-story-close's JIT-next gate (Step 7b worktree cleanup):
    given the just-closed CURRENT_BRANCH, return the story-NNN id so
    we can locate the matching teammate worktree. Returns None for
    branches that don't match the convention (free branches, plan
    branches, primary branches).
    """

    def test_user_prefix_with_slug(self):
        self.assertEqual(
            identity.extract_story_id("paul/story-001-jit-branches"),
            "story-001",
        )

    def test_user_prefix_no_slug(self):
        # Slug-less variants (e.g. older spawn_teammate output) still
        # match — the trailing hyphen + slug is optional.
        self.assertEqual(
            identity.extract_story_id("paul/story-042"),
            "story-042",
        )

    def test_three_digit_story_id(self):
        self.assertEqual(
            identity.extract_story_id("alice/story-100-feature"),
            "story-100",
        )

    def test_no_user_prefix(self):
        # Non-conforming branch — return None.
        self.assertIsNone(identity.extract_story_id("story-001-direct"))

    def test_free_branch(self):
        self.assertIsNone(
            identity.extract_story_id("paul/free-2026-04-30-jit-branches")
        )

    def test_plan_branch(self):
        self.assertIsNone(identity.extract_story_id("paul/plan-auth"))

    def test_primary_branch(self):
        self.assertIsNone(identity.extract_story_id("main"))

    def test_empty_string(self):
        self.assertIsNone(identity.extract_story_id(""))

    def test_non_digit_story_number_rejected(self):
        # Locks in the `\d+` precision — `story-abc` is not a story
        # branch even with the correct user-prefix shape.
        self.assertIsNone(identity.extract_story_id("paul/story-abc"))

    def test_no_digits_after_story_prefix_rejected(self):
        self.assertIsNone(identity.extract_story_id("paul/story-"))


if __name__ == "__main__":
    unittest.main()
