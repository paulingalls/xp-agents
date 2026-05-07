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

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    init_repo,
    init_repo_in_spaced_parent,
    seed_sprint_with_stories,
)
from conftest import _IntegrationTestCase
from integration.conftest import _XP_STORY_CLOSE_PRELOAD

_PRELOAD_BASE = _PLUGIN_ROOT / "skills" / "_preload_base.sh"
_XP_QUALITY_REVIEW_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
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


# [story-004] Removed ACCEPT_ACTIVE marker test surface entirely.
# close-then-done makes the marker structurally moot:
#   - TestXpAcceptPreloadAcceptActive (preload no longer arms)
#   - _ClosePreloadAcceptActiveMixin + Plan/Free subclasses (preloads
#     no longer consume — marker doesn't exist)
#   - TestXpStoryClosePreloadPreservesAcceptActive (story-003 inverse pin
#     also moot once marker is gone)
#   - TestXpKickoffPreloadAcceptActive (defensive cleanup removed since
#     there's no marker to defend against)
# pre_tool_write re-arm protection now uses sprint_state.has_reviewing_stories
# directly — pinned in test_pre_tool_write_gates.py.


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

    # [story-004] Removed 4 auto-detect tests entirely. Per decision
    # 798a27b425a7: xp-quality-review preload no longer auto-detects
    # teammate worktree from sprint state — caller sets TEAMMATE_CWD
    # explicitly when invoking quality-review during a fix-cycle. The
    # surviving tests (test_xp_quality_review_preload_honors_teammate_cwd
    # + test_xp_quality_review_preload_default_when_no_teammate_cwd)
    # pin the explicit-pass-through contract.
