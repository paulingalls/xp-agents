#!/usr/bin/env python3
"""Tests for identity.py — agent identity resolution utilities.

Covers: resolve_agent_id, is_worktree_teammate, get_current_branch, user_namespace.
"""

import json
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
from _sprint_fixtures import write_system_context


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
            # An SMM dir with no system_context.json — pins the git-derived
            # answer WITHOUT depending on whatever SMM the ambient environment
            # resolves to. Omitting it made this test read the developer's real
            # system_context (and fail under `python3 -m unittest discover`,
            # which loads no conftest and so gets no redirected plugin-data
            # root).
            result = identity.user_namespace(td, smm_dir=Path(td))
            self.assertEqual(result, "test")


class TestUserNamespaceFromSystemContext(unittest.TestCase):
    """A recorded branching_strategy.user_namespace OVERRIDES the git-derived slug.

    Before this, the recorded field was inert: system_context could say
    ``paulingalls`` while every branch was created as ``ingallsp/...`` and
    nothing reported the disagreement. The recorded value is user-editable
    (``system_context_cli edit-branching-field``), so it is an override, and an
    override that nothing reads is a lie.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write_ctx(self, **bs_extras: object) -> None:
        """Fully-valid context via the shared fixture — a schema-invalid doc
        makes the loader raise, which this code treats as "no override", so a
        hand-rolled minimal doc would make every assertion below pass
        vacuously."""
        write_system_context(self.smm_dir, 2, **bs_extras)

    def _git_says(self, email: str):
        return patch(
            "identity.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=f"{email}\n"),
        )

    def test_recorded_value_wins_over_git_email(self):
        self._write_ctx(user_namespace="paulingalls")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "paulingalls"
            )

    def test_absent_field_falls_back_to_git(self):
        self._write_ctx()
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_no_system_context_falls_back_to_git(self):
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_empty_string_falls_back_to_git(self):
        self._write_ctx(user_namespace="   ")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_leading_dash_is_refused_and_falls_back(self):
        """A namespace reaching `git branch` as argv must never start with `-`.

        Same argv-injection guard integration_branch already carries: the value
        is interpolated into a branch name handed to git, so a leading dash
        would arrive as a FLAG.
        """
        self._write_ctx(user_namespace="--upload-pack=evil")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_unusable_ref_characters_fall_back(self):
        self._write_ctx(user_namespace="has spaces")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_omitted_smm_dir_self_resolves_the_override(self):
        """The 10 existing call sites pass no smm_dir and must STILL see the
        override — branch readers (list_user_branches) and branch writers
        (create_free_branch) both go through this path, and a reader that
        disagreed with the writer would break kickoff's orphan triage.

        SMM_DIR is pinned rather than left to init.sh derivation: unpinned,
        this reads whatever SMM the ambient environment resolves to (the
        developer's own, under `python3 -m unittest discover`).
        """
        self._write_ctx(user_namespace="paulingalls")
        with (
            patch.dict(os.environ, {"SMM_DIR": str(self.smm_dir)}),
            self._git_says("ingallsp@example.com"),
        ):
            self.assertEqual(identity.user_namespace("/tmp"), "paulingalls")

    def test_multi_segment_namespace_falls_back(self):
        """A namespace is ONE segment: `team/paul` would create
        `team/paul/free-…` branches that `is_free_branch` / `extract_story_id`
        (both `^[^/]+/…`) cannot recognize, so free-close and story-close would
        refuse the plugin's own branches. Dropped here, refused at write time.
        """
        self._write_ctx(user_namespace="team/paul")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_schema_invalid_context_falls_back_instead_of_raising(self):
        """A DELIBERATE tradeoff, pinned so it is not mistaken for an accident.

        The override is read through the validating loader (which also carries
        the symlink guard), so a system_context that fails schema validation
        anywhere drops the namespace override rather than honoring just this
        field. Branch naming must never raise, and git-derived is always a
        valid answer. The cost: an unrelated invalid field silently changes the
        branch prefix — acceptable only because a schema-invalid context is
        already loudly broken everywhere else that reads it.
        """
        (self.smm_dir / "system_context.json").write_text(
            json.dumps({"product": {"name": "t", "purpose": "t"}})
        )
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )

    def test_corrupt_json_falls_back_instead_of_raising(self):
        (self.smm_dir / "system_context.json").write_text("{not json")
        with self._git_says("ingallsp@example.com"):
            self.assertEqual(
                identity.user_namespace("/tmp", smm_dir=self.smm_dir), "ingallsp"
            )


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
