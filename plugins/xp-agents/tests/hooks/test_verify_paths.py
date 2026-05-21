#!/usr/bin/env python3
"""Tests for scripts/verify_paths.py.

The module codifies the harness path-parsing rules that previously lived
only as prose in agents/xp-plan-reviewer.md (§10b). It exposes:
- extract_verify_paths(story): the set of test-file paths a story's per-AC
  verify objects and story-level acceptance_execution point at.
- untouched_verify_paths(paths, cwd, base): the declared paths that no
  commit on base..HEAD touched (log-walk, so touch-then-revert still counts
  as touched).
- a CLI for the story-close preload.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
import verify_paths
from _bases import _TempRepoTestCase
from conftest import make_sprint_dict, make_story_dict, run_cli

_VERIFY_PATHS = Path(__file__).parent.parent.parent / "scripts" / "verify_paths.py"


class TestExtractPathsFromCommand(unittest.TestCase):
    def test_pytest_strips_selector(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "pytest tests/hooks/test_x.py::TestC::test_m"
            ),
            {"tests/hooks/test_x.py"},
        )

    def test_python_m_pytest_multiple_paths(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "python -m pytest tests/a.py tests/b.py"
            ),
            {"tests/a.py", "tests/b.py"},
        )

    def test_pytest_flags_and_flag_args_ignored(self):
        # -x is a bare flag; -k consumes its expr argument — neither is a path.
        self.assertEqual(
            verify_paths._extract_paths_from_command("pytest -x -k expr tests/a.py"),
            {"tests/a.py"},
        )

    def test_unittest_discover_start_and_top_dirs(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command(
                "python -m unittest discover -s tests/smm -t tests"
            ),
            {"tests/smm", "tests"},
        )

    def test_direct_python_script(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("python scripts/foo.py"),
            {"scripts/foo.py"},
        )

    def test_direct_bash_script(self):
        self.assertEqual(
            verify_paths._extract_paths_from_command("bash run.sh"),
            {"run.sh"},
        )

    def test_unrecognized_runner_yields_nothing(self):
        self.assertEqual(verify_paths._extract_paths_from_command("echo hello"), set())

    def test_runner_with_no_path_yields_nothing(self):
        self.assertEqual(verify_paths._extract_paths_from_command("pytest"), set())


class TestExtractVerifyPaths(unittest.TestCase):
    def test_story_level_acceptance_execution(self):
        story = make_story_dict(
            acceptance_criteria=["a manual string AC"],
            acceptance_execution={"type": "pytest", "command": "pytest tests/b.py"},
        )
        self.assertEqual(verify_paths.extract_verify_paths(story), {"tests/b.py"})

    def test_per_ac_objects_union_with_story_level(self):
        story = make_story_dict(
            acceptance_criteria=[
                "a manual string AC",
                {"description": "x", "command": "pytest tests/a.py"},
                {"description": "y", "commands": ["pytest tests/c.py", "bash s.sh"]},
            ],
            acceptance_execution={"type": "pytest", "command": "pytest tests/b.py"},
        )
        self.assertEqual(
            verify_paths.extract_verify_paths(story),
            {"tests/a.py", "tests/b.py", "tests/c.py", "s.sh"},
        )

    def test_string_only_acs_no_execution_is_empty(self):
        story = make_story_dict(
            acceptance_criteria=["manual 1", "E2E: manual 2"],
        )
        story.pop("acceptance_execution", None)
        self.assertEqual(verify_paths.extract_verify_paths(story), set())


class _GitRepoCase(_TempRepoTestCase):
    """Adds per-test git-commit helpers atop the shared temp repo."""

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
            env=self._test_env,
        )

    def _commit_file(self, relpath: str, content: str, message: str) -> None:
        target = self.tmpdir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self._git("add", relpath)
        self._git("commit", "-m", message)

    def _delete_file(self, relpath: str, message: str) -> None:
        self._git("rm", relpath)
        self._git("commit", "-m", message)

    def _head(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        ).stdout.strip()


class TestUntouchedVerifyPaths(_GitRepoCase):
    def test_reports_only_untouched_paths(self):
        self._commit_file("seed1.txt", "x", "seed")
        base = self._head()
        self._commit_file("a/x.py", "code", "touch a/x.py")
        self.assertEqual(
            verify_paths.untouched_verify_paths(
                {"a/x.py", "b/y.py"}, str(self.tmpdir), base
            ),
            ["b/y.py"],
        )

    def test_touch_then_revert_still_counts_as_touched(self):
        self._commit_file("seed2.txt", "x", "seed")
        base = self._head()
        self._commit_file("c/z.py", "code", "add c/z.py")
        self._delete_file("c/z.py", "revert c/z.py")
        # Net diff base..HEAD shows nothing, but the path WAS touched on the
        # branch — the log-walk must still clear it.
        self.assertEqual(
            verify_paths.untouched_verify_paths({"c/z.py"}, str(self.tmpdir), base),
            [],
        )

    def test_file_inside_declared_directory_counts_as_touched(self):
        self._commit_file("seed3.txt", "x", "seed")
        base = self._head()
        self._commit_file("tests/hooks/test_new.py", "code", "touch nested file")
        self.assertEqual(
            verify_paths.untouched_verify_paths(
                {"tests/hooks/"}, str(self.tmpdir), base
            ),
            [],
        )

    def test_git_failure_raises(self):
        with self.assertRaises(ValueError):
            verify_paths.untouched_verify_paths(
                {"a.py"}, str(self.tmpdir), "no-such-ref-xyz"
            )


class TestVerifyPathsCLI(_GitRepoCase):
    def _save_story(self) -> None:
        smm_dir = self._get_smm_dir()
        story = make_story_dict(
            acceptance_execution={"type": "pytest", "command": "pytest a/x.py"}
        )
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

    def _run(self, base: str):
        return run_cli(
            _VERIFY_PATHS,
            ["--cwd", str(self.tmpdir), "--story", "story-001", "--base", base],
            self._get_smm_dir(),
        )

    def test_untouched_path_reported_and_exit_1(self):
        self._save_story()
        self._commit_file("seed_cli1.txt", "x", "seed")
        base = self._head()
        self._commit_file("unrelated.py", "code", "touch unrelated")
        result = self._run(base)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("a/x.py", result.stdout)

    def test_touched_path_clean_exit_0(self):
        self._save_story()
        self._commit_file("seed_cli2.txt", "x", "seed")
        base = self._head()
        self._commit_file("a/x.py", "code", "touch the verify path")
        result = self._run(base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
