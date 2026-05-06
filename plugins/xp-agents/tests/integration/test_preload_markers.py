#!/usr/bin/env python3
"""Integration tests for write_marker / consume_marker in _preload_base.sh.

Exercises the shell wrappers with shell-sensitive characters in content
to catch string-interpolation fragility (single/double quotes, backslashes).
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from _branching_fixtures import (
    init_repo,
    init_repo_in_spaced_parent,
    seed_sprint_with_stories,
)
from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_IN_PROGRESS,
    _IntegrationTestCase,
    _MixinBase,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD_BASE = _PLUGIN_ROOT / "skills" / "_preload_base.sh"
_XP_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"
_XP_PLAN_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"
)
_XP_FREE_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"
)
_XP_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)
_XP_QUALITY_REVIEW_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
)
_XP_KICKOFF_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"
)


class TestMarkerShellHelpers(_IntegrationTestCase):
    def _run_shell(self, cmd: str) -> subprocess.CompletedProcess:
        """Source _preload_base.sh and run a shell command in that context."""
        script = f"set -e\nsource {_PRELOAD_BASE}\n{cmd}\n"
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )

    def test_write_marker_preserves_tricky_content(self):
        cases = [
            ("single_quote", "what's up"),
            ("backslash", r"path\with\backslashes"),
            ("double_quote", 'say "hi" now'),
            ("mixed", 'it\'s a "test" with \\backslash'),
        ]
        for name, tricky in cases:
            with self.subTest(case=name):
                result = self._run_shell(
                    f"write_marker NEEDS_HOUSEKEEPING {shlex.quote(tricky)}"
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                marker_path = self.smm_dir / markers.NEEDS_HOUSEKEEPING.name
                self.assertTrue(
                    marker_path.exists(),
                    f"marker not written; stderr={result.stderr}",
                )
                self.assertEqual(marker_path.read_text(encoding="utf-8"), tricky)
                marker_path.unlink()

    def test_consume_marker_removes_file(self):
        tricky = "hello 'world'"
        result = self._run_shell(
            f"write_marker NEEDS_HOUSEKEEPING {shlex.quote(tricky)}\n"
            f"consume_marker NEEDS_HOUSEKEEPING"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        marker_path = self.smm_dir / markers.NEEDS_HOUSEKEEPING.name
        self.assertFalse(marker_path.exists())


class TestXpAcceptPreloadAcceptActive(_IntegrationTestCase):
    """xp-accept preload arms ACCEPT_ACTIVE iff there are in-progress stories."""

    def test_arms_marker_when_in_progress(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"stdout={result.stdout}",
        )

    def test_skips_marker_when_no_in_progress(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"stdout={result.stdout}",
        )


class _ClosePreloadAcceptActiveMixin(_MixinBase):
    """Shared assertions for close-skill preloads that consume ACCEPT_ACTIVE.

    Three close-skill preloads (sprint, plan, free) consume ACCEPT_ACTIVE
    on entry so the marker cannot strand across sessions when an
    alternate close path fires. Idempotent when the marker is absent.

    NOTE: xp-story-close does NOT consume the marker under close-then-done
    semantics — pinned separately by `TestXpStoryClosePreloadPreservesAcceptActive`
    (preservation is the load-bearing inverse contract: consuming early
    leaves subsequent /xp-accept fix-cycles unprotected).

    Subclasses set `_PRELOAD` and inherit `_IntegrationTestCase` for
    smm_dir / tmpdir / _run_preload.
    """

    _PRELOAD: Path
    if TYPE_CHECKING:
        smm_dir: Path

        def _run_preload(
            self,
            script_path: Path,
            extra_env: dict | None = None,
        ) -> subprocess.CompletedProcess: ...

    def test_consumes_marker_when_present(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"marker not consumed; stdout={result.stdout}",
        )

    def test_idempotent_when_absent(self):
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))


class TestXpPlanClosePreloadAcceptActive(
    _ClosePreloadAcceptActiveMixin, _IntegrationTestCase
):
    _PRELOAD = _XP_PLAN_CLOSE_PRELOAD


class TestXpFreeClosePreloadAcceptActive(
    _ClosePreloadAcceptActiveMixin, _IntegrationTestCase
):
    _PRELOAD = _XP_FREE_CLOSE_PRELOAD


class TestXpStoryClosePreloadPreservesAcceptActive(_IntegrationTestCase):
    """xp-story-close preload PRESERVES ACCEPT_ACTIVE under close-then-done.

    The marker stays armed throughout the per-story close cycle so
    /xp-accept fix-cycles inside /xp-story-close remain protected
    against .accept re-arm. xp-sprint-close consumes the marker at
    end-of-flow. Inverse pin guards against a future regression that
    re-introduces the early consume in xp-story-close.
    """

    def test_preserves_marker_when_present(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        result = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"marker MUST persist; stdout={result.stdout}",
        )

    def test_idempotent_when_absent(self):
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        result = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))


class TestXpKickoffPreloadAcceptActive(_IntegrationTestCase):
    """xp-kickoff defensively clears ACCEPT_ACTIVE when no in-progress
    stories remain (catches crash/abandon between xp-accept and a close
    skill firing). MUST preserve the marker when in-progress stories exist
    so an active acceptance session resumed mid-flight is not clobbered.
    """

    def test_consumes_marker_when_no_in_progress(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"marker not consumed; stdout={result.stdout}",
        )

    def test_preserves_marker_when_in_progress(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=(
                "marker incorrectly consumed while in-progress stories exist; "
                f"stdout={result.stdout}"
            ),
        )

    def test_consumes_marker_when_no_sprint(self):
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        # No sprint.json at all — sprint completed externally / never started.
        # in_progress_count must be 0 in this branch and marker should clear.
        result = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"marker not consumed when no sprint; stdout={result.stdout}",
        )

    def test_idempotent_when_absent(self):
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        result = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))


class TestXpStoryClosePreloadSpaceInPath(unittest.TestCase):
    """xp-story-close preload teammate-discovery survives space-in-path.

    Contract pin for the tab-delimited emit from
    ``find-closing-teammate-worktree`` and its bash split in the preload.
    Note: the prior space-delimited form happened to parse correctly
    because git refs cannot contain spaces (``${CLOSING% *}`` strips a
    single trailing space-prefixed branch); this test pins the now-
    explicit tab contract so a future change to either side is caught.

    Standalone class (not _IntegrationTestCase) — the shared fixture pins
    a single tmp git repo per class and tempfile.mkdtemp paths never
    contain spaces; we need a fresh per-test repo under a custom parent
    dir we create with a space in its name.
    """

    def setUp(self):
        self._parent = Path(tempfile.mkdtemp(prefix="path-space-"))
        self._plugin_data = Path(tempfile.mkdtemp(prefix="path-space-pd-"))
        self.repo = Path(init_repo_in_spaced_parent(str(self._parent)))

        plugin_root = Path(__file__).parent.parent.parent
        self._test_env = os.environ.copy()
        self._test_env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data)
        init_sh = plugin_root / "smm" / "init.sh"
        result = subprocess.run(
            ["bash", str(init_sh)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        )
        self.smm_dir = Path(result.stdout.strip())
        self._test_env["SMM_DIR"] = str(self.smm_dir)

    def tearDown(self):
        # Ensure worktree git metadata releases the path before the parent rm.
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True)
        shutil.rmtree(self._parent, ignore_errors=True)
        shutil.rmtree(self._plugin_data, ignore_errors=True)

    def _make_teammate_worktree(self, story_id: str, branch: str) -> str:
        path = self.repo / ".claude" / "worktrees" / f"worktree-{story_id}"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(path), "HEAD"],
            cwd=self.repo,
            capture_output=True,
            check=True,
        )
        return os.path.realpath(str(path))

    def test_preload_emits_teammate_cwd_and_branch(self):
        # Close-then-done: xp-story-close discovers the in-`reviewing`
        # story (mark-done is the FINAL step after merge).
        seed_sprint_with_stories(self.smm_dir, [("story-001", "reviewing")])
        wt_path = self._make_teammate_worktree("story-001", "u/story-001-reviewing")
        self.assertIn(" ", wt_path)

        result = subprocess.run(
            ["bash", str(_XP_STORY_CLOSE_PRELOAD)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # First occurrence wins; preload's KEY=VALUE field block is
        # emitted before the shared close-pipeline md is appended, so
        # keys are stable.
        fields = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                fields.setdefault(k, v)
        self.assertEqual(
            fields.get("TEAMMATE_CWD"),
            wt_path,
            msg=f"path lost spaces; stdout={result.stdout!r}",
        )
        self.assertEqual(
            fields.get("CURRENT_BRANCH"),
            "u/story-001-reviewing",
            msg=f"branch parse drift; stdout={result.stdout!r}",
        )


class TestPreloadHonorsTeammateCwd(unittest.TestCase):
    """``dump_diff`` and ``get_changed_files`` honor ``TEAMMATE_CWD``.

    During ``/xp-accept`` teammate fix-cycles the orchestrator may
    invoke ``/xp-quality-review`` while sitting in the main checkout —
    the actual diff lives at ``.claude/worktrees/worktree-<story-id>``
    while the orchestrator's cwd may carry unrelated unstaged state.
    With ``TEAMMATE_CWD`` set the helpers route ``git -C <cwd>`` so the
    reviewer sees the teammate's diff, not the orchestrator's incidentals.

    Standalone class (not ``_IntegrationTestCase``) — the shared
    fixture is per-class and we need a fresh repo with a fresh worktree
    on every test method to keep diff state hermetic.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="preload-cwd-"))
        self._plugin_data = Path(tempfile.mkdtemp(prefix="preload-cwd-pd-"))
        init_repo(str(self.tmpdir))

        self._test_env = os.environ.copy()
        self._test_env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data)
        # Strip leaks from a developer shell that would steer git or SMM.
        for var in ("TEAMMATE_CWD", "SMM_DIR", "GIT_DIR", "GIT_WORK_TREE"):
            self._test_env.pop(var, None)

        init_sh = _PLUGIN_ROOT / "smm" / "init.sh"
        result = subprocess.run(
            ["bash", str(init_sh)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        )
        self.smm_dir = Path(result.stdout.strip())
        self._test_env["SMM_DIR"] = str(self.smm_dir)

        self.wt_path = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        self.wt_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "u/story-001",
                str(self.wt_path),
                "HEAD",
            ],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Orchestrator carries an unstaged file; teammate worktree carries
        # a distinct staged file. Distinct names + content so the test can
        # assert on file presence in the diff/listing without ambiguity.
        (self.tmpdir / "orchestrator_only.txt").write_text("orch-content\n")
        (self.wt_path / "worktree_only.txt").write_text("wt-content\n")
        subprocess.run(
            ["git", "add", "worktree_only.txt"],
            cwd=self.wt_path,
            capture_output=True,
            check=True,
        )

    def tearDown(self):
        # Release worktree git metadata before removing the parent so the
        # main repo's `.git/worktrees/` registry doesn't outlive its dirs.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.wt_path)],
            cwd=self.tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "prune"], cwd=self.tmpdir, capture_output=True
        )
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self._plugin_data, ignore_errors=True)

    def _run_shell(
        self, cmd: str, env_extra: dict | None = None
    ) -> subprocess.CompletedProcess:
        script = f"set -e\nsource {_PRELOAD_BASE}\n{cmd}\n"
        env = self._test_env.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_dump_diff_routes_to_teammate_cwd_when_set(self):
        # AC2: TEAMMATE_CWD points at the worktree → dump_diff captures the
        # worktree's staged file, not the orchestrator's unstaged file.
        result = self._run_shell(
            "dump_diff full",
            env_extra={"TEAMMATE_CWD": str(self.wt_path)},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("worktree_only.txt", result.stdout)
        self.assertNotIn("orchestrator_only.txt", result.stdout)

    def test_dump_diff_default_unchanged_when_unset(self):
        # AC1: TEAMMATE_CWD unset → dump_diff captures orchestrator's cwd
        # state. Preserves prior behavior for every existing caller.
        result = self._run_shell("dump_diff full")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("orchestrator_only.txt", result.stdout)
        self.assertNotIn("worktree_only.txt", result.stdout)

    def test_get_changed_files_routes_to_teammate_cwd_when_set(self):
        result = self._run_shell(
            "get_changed_files",
            env_extra={"TEAMMATE_CWD": str(self.wt_path)},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        files = result.stdout.split()
        self.assertIn("worktree_only.txt", files)
        self.assertNotIn("orchestrator_only.txt", files)

    def test_get_changed_files_default_unchanged_when_unset(self):
        result = self._run_shell("get_changed_files")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        files = result.stdout.split()
        self.assertIn("orchestrator_only.txt", files)
        self.assertNotIn("worktree_only.txt", files)

    def test_dump_diff_empty_teammate_cwd_falls_back_to_default(self):
        # ``TEAMMATE_CWD=`` (set but empty) must behave identically to unset
        # so callers can safely re-export the variable without a guard.
        result = self._run_shell(
            "dump_diff full",
            env_extra={"TEAMMATE_CWD": ""},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("orchestrator_only.txt", result.stdout)
        self.assertNotIn("worktree_only.txt", result.stdout)

    def test_xp_quality_review_preload_honors_teammate_cwd(self):
        # AC3 (E2E): Driven through the actual xp-quality-review preload —
        # with TEAMMATE_CWD pointing at the worktree, dump_diff in the
        # rendered output reflects the worktree's staged file and the
        # orchestrator's incidental edit does not appear.
        env = self._test_env.copy()
        env["TEAMMATE_CWD"] = str(self.wt_path)
        result = subprocess.run(
            ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("worktree_only.txt", result.stdout)
        self.assertNotIn("orchestrator_only.txt", result.stdout)

    def test_xp_quality_review_preload_default_when_no_teammate_cwd(self):
        # Inverse of the above: no TEAMMATE_CWD → preload reports
        # orchestrator's cwd (current behavior, unchanged).
        result = subprocess.run(
            ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("orchestrator_only.txt", result.stdout)
        self.assertNotIn("worktree_only.txt", result.stdout)

    def _seed_in_progress_sprint(self, story_ids: list[str]) -> None:
        seed_sprint_with_stories(
            self.smm_dir, [(sid, "in-progress") for sid in story_ids]
        )

    def test_preload_auto_detects_teammate_cwd_in_fix_cycle(self):
        # Fix-cycle context: ACCEPT_ACTIVE marker present + exactly one
        # in-progress story with a live teammate worktree → preload sets
        # TEAMMATE_CWD to that worktree so dump_diff captures the
        # teammate's diff. Mirrors what /xp-accept's "Debug and re-run"
        # branch sets up before invoking /xp-quality-review.
        self._seed_in_progress_sprint(["story-001"])
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")

        result = subprocess.run(
            ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("worktree_only.txt", result.stdout)
        self.assertNotIn("orchestrator_only.txt", result.stdout)

    def test_preload_skips_auto_detection_without_accept_active(self):
        # Marker absent → not a fix-cycle, even if a teammate worktree
        # exists for an in-progress story (e.g. teammate is mid-work and
        # the orchestrator runs /xp-quality-review on its OWN edits).
        self._seed_in_progress_sprint(["story-001"])

        result = subprocess.run(
            ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("orchestrator_only.txt", result.stdout)
        self.assertNotIn("worktree_only.txt", result.stdout)

    def test_preload_skips_auto_detection_when_ambiguous(self):
        # Multiple in-progress stories with live worktrees → cannot
        # disambiguate which is the fix-cycle target; fall back to
        # orchestrator's cwd rather than guess.
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                "u/story-002",
                str(wt2),
                "HEAD",
            ],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        try:
            self._seed_in_progress_sprint(["story-001", "story-002"])
            markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")

            result = subprocess.run(
                ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
                cwd=self.tmpdir,
                capture_output=True,
                text=True,
                env=self._test_env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("orchestrator_only.txt", result.stdout)
            self.assertNotIn("worktree_only.txt", result.stdout)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt2)],
                cwd=self.tmpdir,
                capture_output=True,
            )

    def test_preload_explicit_teammate_cwd_wins_over_auto_detection(self):
        # Even with ACCEPT_ACTIVE marker present, an explicitly-set
        # TEAMMATE_CWD must not be overwritten by detection — the caller
        # (orchestrator script, test harness) knows better than the
        # heuristic.
        self._seed_in_progress_sprint(["story-001"])
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")

        env = self._test_env.copy()
        env["TEAMMATE_CWD"] = str(self.wt_path)
        result = subprocess.run(
            ["bash", str(_XP_QUALITY_REVIEW_PRELOAD)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("worktree_only.txt", result.stdout)
        self.assertNotIn("orchestrator_only.txt", result.stdout)
