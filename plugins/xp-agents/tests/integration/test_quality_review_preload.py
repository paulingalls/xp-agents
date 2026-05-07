#!/usr/bin/env python3
"""xp-quality-review preload TEAMMATE_CWD auto-detect (concern 4886fe014abb).

Caller-set TEAMMATE_CWD always wins (explicit pass-through, decision
798a27b425a7). When unset, auto-detect routes to a teammate worktree
ONLY when the orchestrator has zero uncommitted changes AND exactly
one teammate worktree has changes. This narrow trigger avoids the
hijack risk that motivated removing the prior auto-detect: an
orchestrator with its own in-flight work is never overridden.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _bases import _PLUGIN_ROOT
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
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Mirror real-repo .gitignore — without this, the orchestrator's
        # untracked-files check sees the .claude/worktrees/ dir itself
        # (which contains teammate worktrees) and reports the orchestrator
        # as "dirty", defeating the hijack-guard. Done once at class level
        # because per-test setUp wipes the worktree but not .git's HEAD —
        # a per-test re-add+commit would no-op the second test (file
        # restored to HEAD content) and break check=True.
        gitignore = cls.tmpdir / ".gitignore"
        gitignore.write_text(".claude/worktrees/\n")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=str(cls.tmpdir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "test: gitignore worktrees"],
            cwd=str(cls.tmpdir),
            capture_output=True,
            check=True,
        )
        # Refresh _IntegrationTestCase's snapshot to include the new HEAD
        # state (the base setUpClass snapshotted SMM dir contents only;
        # tmpdir HEAD is unaffected by per-test setUp restore).

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
        # Per-test setUp wiped .gitignore from worktree (it's not in the
        # base's preserve-list). Restore from HEAD so the orchestrator
        # is clean for tests that depend on the hijack-guard.
        subprocess.run(
            ["git", "checkout", "--", ".gitignore"],
            cwd=str(self.tmpdir),
            capture_output=True,
            check=True,
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
        # Mirror identity._TEAMMATE_PREFIX naming (`worktree-story-NNN`)
        # so the preload's awk pattern matches.
        wt_path = self.tmpdir / ".claude" / "worktrees" / f"worktree-story-{story_id}"
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "-b", f"story-{story_id}", str(wt_path)],
            cwd=str(self.tmpdir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed: {result.stderr}\n{result.stdout}"
            )
        return wt_path

    def _stage_change_in(self, path: Path, filename: str = "scratch.py") -> None:
        (path / filename).write_text("x = 1\n")

    def test_no_teammate_worktrees_yields_empty_teammate_cwd(self):
        """Solo flow: orchestrator has its own diff, no auto-detect target."""
        self._stage_change_in(self.tmpdir)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_orchestrator_has_diff_blocks_auto_detect(self):
        """Hijack guard: when orchestrator has any uncommitted work, do NOT
        auto-route to teammate even if a teammate worktree has changes."""
        wt = self._make_teammate_worktree("042")
        self._stage_change_in(self.tmpdir, "orch.py")
        self._stage_change_in(wt, "team.py")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_orchestrator_clean_one_teammate_with_diff_auto_detects(self):
        """Trigger case: orchestrator clean + exactly one teammate has
        changes → auto-set TEAMMATE_CWD to that worktree."""
        wt = self._make_teammate_worktree("042")
        self._stage_change_in(wt, "team.py")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_var(result.stdout, "TEAMMATE_CWD"),
            str(wt.resolve()),
        )

    def test_orchestrator_clean_two_teammates_with_diff_skips_auto_detect(self):
        """Ambiguity guard: 2+ teammate worktrees with changes → empty
        TEAMMATE_CWD (caller must pick explicitly)."""
        wt1 = self._make_teammate_worktree("042")
        wt2 = self._make_teammate_worktree("043")
        self._stage_change_in(wt1, "a.py")
        self._stage_change_in(wt2, "b.py")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_orchestrator_clean_teammate_clean_yields_empty(self):
        """Teammate worktree exists but has no diff → no auto-route."""
        self._make_teammate_worktree("042")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_var(result.stdout, "TEAMMATE_CWD"), "")

    def test_explicit_teammate_cwd_wins_over_auto_detect(self):
        """Caller-set TEAMMATE_CWD is preserved; auto-detect must NOT
        overwrite it. Use a different worktree as the explicit target so
        auto-detect could plausibly pick the other one — preserved-as-set
        is the assertion. Explicit pass-through wins per 798a27b425a7."""
        wt_auto_candidate = self._make_teammate_worktree("042")
        self._stage_change_in(wt_auto_candidate, "team.py")
        wt_explicit = self._make_teammate_worktree("043")
        self._stage_change_in(wt_explicit, "explicit.py")
        result = self._run_preload(
            env_overrides={"TEAMMATE_CWD": str(wt_explicit.resolve())}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_var(result.stdout, "TEAMMATE_CWD"),
            str(wt_explicit.resolve()),
        )


if __name__ == "__main__":
    unittest.main()
