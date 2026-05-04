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
from _branching_fixtures import init_repo_in_spaced_parent, seed_sprint_with_stories
from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_IN_PROGRESS,
    _IntegrationTestCase,
)

# Static-only base for the mixin below: pyright sees unittest.TestCase
# (so self.assertEqual / self.smm_dir / self._run_preload type-check),
# but at runtime the mixin is plain `object` so pytest doesn't auto-
# collect the mixin's test methods in isolation. Mirrors
# _close_fixtures._MixinBase.
if TYPE_CHECKING:
    _MixinBase = unittest.TestCase
else:
    _MixinBase = object

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

    The four close-skill preloads (sprint, plan, free, story) must each
    consume ACCEPT_ACTIVE on entry so the marker cannot strand across
    sessions when an alternate close path fires. Idempotent when the
    marker is absent.

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


class TestXpStoryClosePreloadAcceptActive(
    _ClosePreloadAcceptActiveMixin, _IntegrationTestCase
):
    _PRELOAD = _XP_STORY_CLOSE_PRELOAD


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
        seed_sprint_with_stories(self.smm_dir, [("story-001", "done")])
        wt_path = self._make_teammate_worktree("story-001", "u/story-001-done")
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
            "u/story-001-done",
            msg=f"branch parse drift; stdout={result.stdout!r}",
        )
