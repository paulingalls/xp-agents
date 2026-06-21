#!/usr/bin/env python3
"""xp-quality-review preload TEAMMATE_CWD auto-detect (concern 4886fe014abb).

Caller-set TEAMMATE_CWD always wins (explicit pass-through, decision
798a27b425a7). When unset, auto-detect keys on the sprint-`closing` story —
the same singleton signal /xp-story-close's preload uses
(branching.py find-closing-teammate-worktree). Quality-review runs at
story-close Step 4.5b against the story being closed, so the worktree of the
story whose sprint.json status is `closing` is the correct review target.

This replaces an earlier change-existence heuristic ("orchestrator clean +
exactly one teammate worktree with uncommitted changes") that grabbed
WHICHEVER worktree had changes — mis-targeting a different teammate that
finished in the background. Keying on `closing` status, not dirtiness, ties
detection to the story actually being closed. Two `closing` stories with live
worktrees is a broken /xp-accept iteration → fail loud (the helper raises).
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import seed_sprint_with_stories
from _worktree_fixtures import make_teammate_worktree
from conftest import _IntegrationTestCase

_QR_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"


def _extract_var(stdout: str, name: str) -> str | None:
    """Return the first KEY=VALUE line where KEY matches name, value side."""
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


class TestQualityReviewPreloadTeammateAutoDetect(_IntegrationTestCase):
    def setUp(self):
        super().setUp()
        # Setup wipes .claude/ but leaves git's worktree registry stale —
        # prune so prior tests' entries don't conflict with new adds.
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(self.tmpdir),
            capture_output=True,
        )
        for sid in ("042", "043", "044"):
            subprocess.run(
                ["git", "branch", "-D", f"story-{sid}"],
                cwd=str(self.tmpdir),
                capture_output=True,
            )

    def _run_preload(
        self, env_overrides: dict | None = None
    ) -> subprocess.CompletedProcess:
        env = self._test_env.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(_QR_PRELOAD)],
            cwd=str(self.tmpdir),
            capture_output=True,
            text=True,
            env=env,
        )

    def _make_teammate_worktree(self, story_id: str) -> Path:
        # Adapt the digit-only story_id convention (e.g., "042") to the
        # canonical helper which expects the full "story-NNN" form so
        # the resulting worktree dir matches identity._TEAMMATE_PREFIX.
        return make_teammate_worktree(
            self.tmpdir, f"story-{story_id}", f"story-{story_id}"
        )

    def _stage_change_in(self, path: Path, filename: str = "scratch.py") -> None:
        (path / filename).write_text("x = 1\n")

    def test_closing_story_with_worktree_auto_detects(self):
        """The story being closed (status `closing`) has a live worktree →
        auto-set TEAMMATE_CWD to it. Dirtiness is irrelevant: a clean worktree
        still resolves, because detection keys on `closing` status."""
        seed_sprint_with_stories(self.smm_dir, [("story-042", "closing")])
        wt = self._make_teammate_worktree("042")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), str(wt))

    def test_worktree_present_but_story_not_closing_yields_empty(self):
        """A live teammate worktree whose story is NOT `closing` (e.g.
        in-progress, finished in the background) must NOT be auto-selected —
        this is the mis-targeting bug. TEAMMATE_CWD stays empty → review `.`."""
        seed_sprint_with_stories(self.smm_dir, [("story-042", "in-progress")])
        self._make_teammate_worktree("042")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_sprint_present_no_closing_dirty_worktree_yields_empty(self):
        """Regression for the old change-existence heuristic: a single teammate
        worktree with UNCOMMITTED changes but no `closing` story must yield
        empty. The old logic would have auto-selected the dirty worktree;
        keying on `closing` status ignores dirtiness."""
        seed_sprint_with_stories(self.smm_dir, [("story-042", "in-progress")])
        wt = self._make_teammate_worktree("042")
        self._stage_change_in(wt, "team.py")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_no_sprint_yields_empty(self):
        """No sprint.json (solo/standalone) → no closing story → empty."""
        self._make_teammate_worktree("042")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_closing_story_no_worktree_yields_empty(self):
        """Story marked `closing` but no live worktree (solo close) → empty."""
        seed_sprint_with_stories(self.smm_dir, [("story-042", "closing")])
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_explicit_teammate_cwd_wins_over_auto_detect(self):
        """Caller-set TEAMMATE_CWD is preserved; auto-detect must NOT
        overwrite it, even with a closing-story worktree present. Explicit
        pass-through wins per 798a27b425a7."""
        seed_sprint_with_stories(self.smm_dir, [("story-042", "closing")])
        self._make_teammate_worktree("042")
        wt_explicit = self._make_teammate_worktree("043")
        result = self._run_preload(env_overrides={"TEAMMATE_CWD": str(wt_explicit)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), str(wt_explicit))

    def test_two_closing_stories_fail_loud(self):
        """Two `closing` stories with live worktrees signals a broken
        /xp-accept iteration — the helper raises and the CLI exits non-zero;
        `set -e` propagates it so the preload fails loud rather than guessing."""
        seed_sprint_with_stories(
            self.smm_dir, [("story-042", "closing"), ("story-043", "closing")]
        )
        self._make_teammate_worktree("042")
        self._make_teammate_worktree("043")
        result = self._run_preload()
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
