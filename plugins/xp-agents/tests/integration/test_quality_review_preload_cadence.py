#!/usr/bin/env python3
"""Integration tests for /xp-quality-review preload cadence-awareness (story-008).

Commit cadence: the preload reviews the staged/unstaged diff (review runs
before the commit) — unchanged. Story cadence: the work is already committed
when /xp-quality-review runs at story-close Step 4.5b, so the preload must
review the cumulative diff against the sprint-branch base (BASE...HEAD), not
the empty staged diff. Falls back to staged behavior when no divergent base
resolves (on-base / stage-0).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from _bases import _PLUGIN_ROOT
from conftest import _IntegrationTestCase

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
_APPEND = _PLUGIN_ROOT / "smm" / "append.sh"


class TestQualityReviewPreloadCadence(_IntegrationTestCase):
    """preload.sh scopes its diff to the sprint-branch range under story cadence."""

    def _git(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.tmpdir, capture_output=True, text=True, check=True
        )

    def _checkout_main_clean(self) -> None:
        # The repo is shared across the class; start each test on a clean main.
        self._git("checkout", "-f", "main")
        subprocess.run(["git", "clean", "-fd"], cwd=self.tmpdir, capture_output=True)

    def _set_cadence(self, value: str) -> None:
        (self.smm_dir / ".review-cadence").write_text(value)

    def _commit_on_branch(self, branch: str, filename: str) -> None:
        self._git("checkout", "-B", branch, "main")
        (self.tmpdir / filename).write_text("x = 1\n")
        self._git("add", filename)
        self._git("commit", "-m", f"add {filename}")

    def test_story_cadence_shows_cumulative_committed_diff(self):
        """AC1: story cadence → diff reflects the committed BASE...HEAD range."""
        self._checkout_main_clean()
        self._commit_on_branch("feature-a", "foo.py")
        self._set_cadence("story")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("foo.py", result.stdout)
        self.assertNotIn("## No Changes", result.stdout)

    def test_commit_cadence_uses_staged_diff(self):
        """AC2: commit cadence → staged behavior, no cumulative range."""
        self._checkout_main_clean()
        (self.tmpdir / "bar.py").write_text("y = 2\n")
        self._git("add", "bar.py")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bar.py", result.stdout)
        self.assertNotIn("cumulative since", result.stdout)

    def test_story_cadence_no_divergence_falls_back(self):
        """AC3: story cadence but on the base (empty range) → graceful staged
        fallback, no error."""
        self._checkout_main_clean()
        self._set_cadence("story")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## No Changes", result.stdout)

    def _extract_var(self, stdout: str, name: str) -> str | None:
        prefix = f"{name}="
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def test_mode_self_find_by_default(self):
        """No fresh /code-review this cycle → MODE=self-find (per-increment)."""
        self._checkout_main_clean()
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "MODE"), "self-find")

    def test_mode_consume_findings_after_code_review(self):
        """simplify_done set (a /code-review ran this cycle) → consume-findings."""
        self._checkout_main_clean()
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "MODE"), "consume-findings")

    def test_story_cadence_changed_files_feed_debt(self):
        """AC4 + E2E: get_changed_files_range surfaces the committed file to the
        Debt section under story cadence."""
        self._checkout_main_clean()
        self._commit_on_branch("feature-b", "baz.py")
        subprocess.run(
            [
                str(_APPEND),
                "--smm-dir",
                str(self.smm_dir),
                "--type",
                "debt",
                "--agent",
                "test",
                "--content",
                "baz needs work",
                "--files",
                '["baz.py"]',
            ],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        )
        self._set_cadence("story")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("baz needs work", result.stdout)
