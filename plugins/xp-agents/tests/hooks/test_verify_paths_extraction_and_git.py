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

Split from test_verify_paths.py for file size management. This file covers
extract_verify_paths (story-dict extraction), untouched_verify_paths (the
git log-walk), and the verify_paths.py CLI. See
test_verify_paths_command_parsing.py for the lower-level
`_extract_paths_from_command` / `classify_path_strategy` parsing tests.
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

    def test_pinned_path_excluded_from_extraction(self):
        story = make_story_dict(
            acceptance_criteria=["a manual string AC"],
            acceptance_execution={
                "type": "pytest",
                "command": "pytest tests/x_test.py",
                "pins": ["tests/x_test.py"],
            },
        )
        self.assertEqual(verify_paths.extract_verify_paths(story), set())

    def test_unpinned_path_still_extracted(self):
        story = make_story_dict(
            acceptance_criteria=["a manual string AC"],
            acceptance_execution={
                "type": "pytest",
                "command": "pytest tests/x_test.py",
            },
        )
        self.assertEqual(verify_paths.extract_verify_paths(story), {"tests/x_test.py"})

    def test_pin_drops_only_exact_match_not_sibling(self):
        # A pin exempts by exact normalized-set membership, never by prefix:
        # pinning tests/a.py must not silently drop the sibling tests/b.py.
        story = make_story_dict(
            acceptance_criteria=[
                {"description": "x", "command": "pytest tests/a.py"},
                {"description": "y", "command": "pytest tests/b.py"},
            ],
            acceptance_execution={
                "type": "pytest",
                "command": "pytest tests/",
                "pins": ["tests/a.py"],
            },
        )
        # tests/a.py pinned+dropped; tests/b.py and the tests/ dir survive.
        self.assertEqual(
            verify_paths.extract_verify_paths(story),
            {"tests/b.py", "tests/"},
        )

    def test_pin_matches_despite_trailing_slash_and_dot_slash(self):
        story = make_story_dict(
            acceptance_criteria=["a manual string AC"],
            acceptance_execution={
                "type": "pytest",
                "command": "pytest tests/x_test.py",
                "pins": ["./tests/x_test.py/"],
            },
        )
        self.assertEqual(verify_paths.extract_verify_paths(story), set())

    def test_cd_prefixed_pin_matches_rebased_token(self):
        story = make_story_dict(
            acceptance_criteria=["a manual string AC"],
            acceptance_execution={
                "type": "pytest",
                "command": "cd apps/x && pytest tests/y_test.py",
                "pins": ["apps/x/tests/y_test.py"],
            },
        )
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


class TestUntouchedVerifyPathsHeadArg(_GitRepoCase):
    """`head=` selects the range end so callers off the branch can check it.

    The close-gate backstop runs at orchestrator cwd ON the target branch, so
    it must walk `target..source`, not the default `base..HEAD` (HEAD=target).
    """

    def test_head_arg_walks_base_to_named_ref(self):
        self._commit_file("seed.txt", "x", "seed")
        base = self._head()
        self._git("checkout", "-b", "feat")
        self._commit_file("a/x.py", "code", "touch a/x.py on feat")
        # Return HEAD to base (detached) — a/x.py is NOT on base..HEAD now.
        self._git("checkout", base)
        # Default head=HEAD (=base): the branch's touch is invisible.
        self.assertEqual(
            verify_paths.untouched_verify_paths({"a/x.py"}, str(self.tmpdir), base),
            ["a/x.py"],
        )
        # head="feat": the branch's touch clears the path.
        self.assertEqual(
            verify_paths.untouched_verify_paths(
                {"a/x.py"}, str(self.tmpdir), base, head="feat"
            ),
            [],
        )


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

    def test_cwd_path_matched_by_any_change(self):
        # A "." declaration (bare unittest discover) means the whole tree —
        # any change on the branch counts as touched (gate fails open).
        self._commit_file("seed4.txt", "x", "seed")
        base = self._head()
        self._commit_file("anything.py", "code", "touch something")
        self.assertEqual(
            verify_paths.untouched_verify_paths({"."}, str(self.tmpdir), base),
            [],
        )

    def test_cd_prefix_command_touch_matches_repo_relative_path(self):
        # Regression for the live monorepo gate failure: a story whose command
        # is `cd apps/agent && pytest tests/` must clear when a commit touches
        # the repo-relative apps/agent/tests/... path.
        self._commit_file("seed_mono.txt", "x", "seed")
        base = self._head()
        self._commit_file("apps/agent/tests/test_x.py", "code", "touch monorepo test")
        story = make_story_dict(
            acceptance_execution={
                "type": "pytest",
                "command": "cd apps/agent && pytest tests/",
            }
        )
        paths = verify_paths.extract_verify_paths(story)
        self.assertEqual(paths, {"apps/agent/tests/"})
        self.assertEqual(
            verify_paths.untouched_verify_paths(paths, str(self.tmpdir), base),
            [],
        )

    def test_playwright_command_enforces_where_it_failed_open(self):
        # Regression for the npx-playwright gap: a story whose acceptance
        # command is `npx playwright test <spec>` must now extract the spec
        # and report it untouched when no commit touches it (previously the
        # parser returned an empty set → silent fail-open).
        self._commit_file("seed_pw.txt", "x", "seed")
        base = self._head()
        self._commit_file("src/unrelated.ts", "code", "touch unrelated")
        story = make_story_dict(
            acceptance_execution={
                "type": "playwright",
                "command": "npx playwright test specs/login.spec.ts",
            }
        )
        paths = verify_paths.extract_verify_paths(story)
        self.assertEqual(paths, {"specs/login.spec.ts"})
        self.assertEqual(
            verify_paths.untouched_verify_paths(paths, str(self.tmpdir), base),
            ["specs/login.spec.ts"],
        )

    def test_script_alias_command_fails_open(self):
        # A path-less script alias maps to the sentinel; any branch change
        # clears it, so the gate never blocks (§10b catches non-verifiable
        # commands at plan-review, not here).
        self._commit_file("seed_alias.txt", "x", "seed")
        base = self._head()
        self._commit_file("anything.ts", "code", "touch something")
        story = make_story_dict(
            acceptance_execution={"type": "jest", "command": "npm run test:e2e"}
        )
        paths = verify_paths.extract_verify_paths(story)
        self.assertEqual(paths, {"."})
        self.assertEqual(
            verify_paths.untouched_verify_paths(paths, str(self.tmpdir), base),
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
