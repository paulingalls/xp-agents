#!/usr/bin/env python3
"""Tests for sprint_cli.py validate-domain: file_domain drift detection.

Split out of test_sprint_cli.py in sprint-108 M1 to keep each test file
under the 500-line cap (decision d027fe5c9066). The CLI is invoked as a
subprocess via run_cli(_CLI, ...), so validate-domain still routes through
sprint_cli.py internally — no import repoint needed.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import GIT_ENV, init_repo
from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


class TestValidateDomainCommand(_SMMTestCase):
    """validate-domain diffs git-changed files (since base) vs declared file_domain.

    Surfaces file_domain drift at story-close commit time instead of
    waiting for the close-reviewer or post-sprint retro (concern
    69fb3b79ca3e).
    """

    def _seed(self, file_domain, story_id="story-001"):
        story = _make_story(id=story_id, file_domain=file_domain)
        sprint = _make_sprint(stories=[story])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def _make_branch_with_changes(self, repo: Path, files):
        """Init repo and add `files` on a feature branch off main."""
        init_repo(str(repo))
        subprocess.run(
            ["git", "checkout", "-b", "story"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        for fn in files:
            target = repo / fn
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n")
            subprocess.run(
                ["git", "add", fn], cwd=repo, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", f"add {fn}"],
                cwd=repo,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )

    def test_clean_match_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner", "src/b.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/b.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("clean", result.stdout.lower())

    def test_single_drift_at_K0_exits_nonzero_and_names_file(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/drift.py", result.stderr)
            self.assertNotIn("src/a.py", result.stderr)

    def test_single_drift_at_default_K1_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # Absorbed-drift signal is emitted on stderr so retros and
            # quality-review can see what slipped past the K-budget.
            self.assertIn("drift (within K=1)", result.stderr)
            self.assertIn("src/drift.py", result.stderr)
            # Stdout must NOT claim "clean" when drift was absorbed —
            # would lie to callers parsing stdout for the clean signal.
            self.assertNotIn("clean", result.stdout)
            self.assertIn("absorbed", result.stdout)

    def test_zero_drift_emits_no_absorbed_signal(self):
        # Clean cases must stay quiet — the absorbed-drift line only
        # fires when 1 <= len(drift) <= tolerance.
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("drift", result.stderr)

    def test_env_read_per_invocation_not_module_global(self):
        # Two back-to-back invocations with different tolerance values
        # against the same story+diff. If XP_FILE_DOMAIN_DRIFT_TOLERANCE
        # were cached at module-import time, the second invocation would
        # inherit the first's tolerance and fail. Subprocess re-import
        # would mask a stale module global, so this test pins the
        # per-invocation contract for any future caller that imports
        # sprint_cli as a library and holds the module across env
        # mutations.
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/drift.py"])
            argv = [
                "validate-domain",
                "story-001",
                "--base",
                "main",
                "--cwd",
                str(repo),
            ]
            strict = run_cli(
                _CLI,
                argv,
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(strict.returncode, 0)
            self.assertIn("src/drift.py", strict.stderr)

            permissive = run_cli(
                _CLI,
                argv,
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "2"},
            )
            self.assertEqual(permissive.returncode, 0, permissive.stderr)
            self.assertIn("drift (within K=2)", permissive.stderr)

    def test_two_drift_at_default_K1_exits_nonzero_and_names_both(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(
                repo, ["src/a.py", "src/drift1.py", "src/drift2.py"]
            )
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/drift1.py", result.stderr)
            self.assertIn("src/drift2.py", result.stderr)
            self.assertNotIn("src/a.py", result.stderr)

    def test_e2e_two_stories_one_sprint_only_over_budget_fails(self):
        # AC4: same sprint.json, two stories. Same git diff seen through
        # each story's file_domain — within-K story passes, over-K fails.
        # Story-001 owns {a, b, drift_x}: changed - declared = {drift_y}
        # = 1 file → within K=1 → exit 0.
        # Story-002 owns {drift_y}: changed - declared = {a, b, drift_x}
        # = 3 files → over K=1 → exit non-zero.
        story_within = _make_story(
            id="story-001",
            file_domain=[
                "src/a.py — owner",
                "src/b.py — owner",
                "src/drift_x.py — owner",
            ],
        )
        story_over = _make_story(id="story-002", file_domain=["src/drift_y.py — owner"])
        sprint = _make_sprint(stories=[story_within, story_over])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(
                repo, ["src/a.py", "src/b.py", "src/drift_x.py", "src/drift_y.py"]
            )
            within_result = run_cli(
                _CLI,
                ["validate-domain", "story-001", "--base", "main", "--cwd", str(repo)],
                self.smm_dir,
            )
            over_result = run_cli(
                _CLI,
                ["validate-domain", "story-002", "--base", "main", "--cwd", str(repo)],
                self.smm_dir,
            )
            self.assertEqual(within_result.returncode, 0, within_result.stderr)
            self.assertNotEqual(over_result.returncode, 0)
            self.assertIn("src/a.py", over_result.stderr)
            self.assertIn("src/b.py", over_result.stderr)
            self.assertIn("src/drift_x.py", over_result.stderr)

    def test_no_commits_on_branch_exits_zero(self):
        self._seed(file_domain=["src/a.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_repo(str(repo))
            # No additional commits — HEAD is still main's initial commit.
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_e2e_third_commit_drift_at_K0_in_stderr(self):
        """E2E: 2-file declared domain + 3rd commit out-of-domain → drift at K=0."""
        self._seed(file_domain=["src/a.py — owner", "src/b.py — owner"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._make_branch_with_changes(repo, ["src/a.py", "src/b.py", "src/c.py"])
            result = run_cli(
                _CLI,
                [
                    "validate-domain",
                    "story-001",
                    "--base",
                    "main",
                    "--cwd",
                    str(repo),
                ],
                self.smm_dir,
                extra_env={"XP_FILE_DOMAIN_DRIFT_TOLERANCE": "0"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("src/c.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
