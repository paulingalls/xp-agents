#!/usr/bin/env python3
"""Tests for scripts/close_common.py — shared close-skill pipeline.

close_common.py exposes 4 subcommands that the close skills (sprint,
plan, free, story) invoke instead of duplicating the same shell idioms
across SKILL.md files:

- preflight: refuse if dirty worktree or current==target
- push: push branch if remote exists, otherwise skip
- create-pr: create PR via gh if available, otherwise skip
- merge: chained merge --no-ff + push target + delete source

Tests are subprocess-based: they invoke close_common.py as a script
against a hermetic temp git repo. gh is stubbed via a fake script on
PATH (see _close_fixtures.stub_gh / stub_no_gh) so tests don't depend
on real GitHub.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import _branching_fixtures as _bf
import _close_fixtures as _cf
from _bases import _PLUGIN_ROOT

_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


def _run(
    args: list[str],
    cwd: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke close_common.py with args. Returns CompletedProcess.

    Uses sys.executable so the subprocess works even when env's PATH
    is scoped to a stub dir (gh-absent test setup).
    """
    return subprocess.run(
        [sys.executable, str(_CLOSE_COMMON), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env if env is not None else _bf.GIT_ENV,
    )


class TestPreflight(unittest.TestCase):
    def test_clean_and_different_branches_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            subprocess.run(
                ["git", "branch", "feature-x"], cwd=td, capture_output=True, check=True
            )
            result = _run(
                ["preflight", "--cwd", td, "--current", "feature-x", "--target", "main"]
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_dirty_worktree_exits_one_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            result = _run(
                ["preflight", "--cwd", td, "--current", "main", "--target", "develop"]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("worktree", result.stderr.lower())
            self.assertIn("clean", result.stderr.lower())

    def test_current_equals_target_exits_one_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = _run(
                ["preflight", "--cwd", td, "--current", "main", "--target", "main"]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("current", result.stderr.lower())
            self.assertIn("target", result.stderr.lower())


class TestPush(unittest.TestCase):
    def test_no_remote_skips_with_message(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = _run(["push", "--cwd", td, "--branch", "main"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skip", result.stdout.lower())
            self.assertIn("remote", result.stdout.lower())

    def test_with_remote_pushes_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _bf.add_bare_remote(td)
            result = _run(["push", "--cwd", td, "--branch", "main"])
            self.assertEqual(result.returncode, 0, result.stderr)
            remotes = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", "main"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("main", remotes.stdout)


class TestCreatePr(unittest.TestCase):
    def test_no_gh_skips_with_message(self):
        with (
            tempfile.TemporaryDirectory() as td,
            tempfile.TemporaryDirectory() as stubd,
        ):
            _bf.init_repo(td)
            env = _cf.stub_no_gh(stubd)
            result = _run(
                [
                    "create-pr",
                    "--cwd",
                    td,
                    "--base",
                    "main",
                    "--head",
                    "feature-x",
                    "--title",
                    "T",
                    "--body",
                    "B",
                ],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skip", result.stdout.lower())
            self.assertIn("gh", result.stdout.lower())

    def test_with_gh_creates_pr_returns_number(self):
        with (
            tempfile.TemporaryDirectory() as td,
            tempfile.TemporaryDirectory() as stubd,
        ):
            _bf.init_repo(td)
            env = _cf.stub_gh(stubd, "https://github.com/owner/repo/pull/4242")
            result = _run(
                [
                    "create-pr",
                    "--cwd",
                    td,
                    "--base",
                    "main",
                    "--head",
                    "feature-x",
                    "--title",
                    "T",
                    "--body",
                    "B",
                ],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "4242")

    def test_returns_number_when_gh_emits_extra_lines(self):
        # gh sometimes emits info/confirmation lines AFTER the PR URL on
        # stdout. cmd_create_pr must locate the URL line specifically —
        # naive `rsplit("/", 1)` against the full stripped stdout
        # returns "<num>\n<trailing-line>" garbage when the trailing
        # line has no slash, and downstream `gh pr diff <PR_NUMBER>`
        # then fails confusingly. Pinning the multi-line case here.
        with (
            tempfile.TemporaryDirectory() as td,
            tempfile.TemporaryDirectory() as stubd,
        ):
            _bf.init_repo(td)
            multiline = (
                "Creating pull request for feature-x into main\n"
                "https://github.com/owner/repo/pull/4242\n"
                "Created pull request\n"
            )
            env = _cf.stub_gh(stubd, multiline)
            result = _run(
                [
                    "create-pr",
                    "--cwd",
                    td,
                    "--base",
                    "main",
                    "--head",
                    "feature-x",
                    "--title",
                    "T",
                    "--body",
                    "B",
                ],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "4242")


class TestMergeReviewCleanGate(unittest.TestCase):
    """--review-clean-cwd backstop (debt e8589ac9a99b): reviewer fixes applied
    during the close review land in the teammate worktree; if left uncommitted,
    the merge + Step 7b worktree removal would silently drop them. The merge
    refuses when the named review target is dirty."""

    def test_dirty_review_target_refuses_merge(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-r", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            # An uncommitted reviewer fix in the review target (untracked, so
            # git merge itself would happily proceed and lose it).
            (Path(td) / "reviewer-fix.txt").write_text("uncommitted")
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-r",
                    "--target",
                    main,
                    "--review-clean-cwd",
                    td,
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncommitted", result.stderr.lower())
            # Merge did NOT happen — source branch survives for a retry.
            self.assertTrue(_bf.branch_exists(td, "feature-r"))

    def test_clean_review_target_allows_merge(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-c", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-c",
                    "--target",
                    main,
                    "--review-clean-cwd",
                    td,
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-c"))

    def test_omitted_review_clean_cwd_skips_check(self):
        # Solo close passes no --review-clean-cwd; a dirty (unrelated) main
        # checkout must NOT block the merge — backward compatible.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-s", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            (Path(td) / "unrelated.txt").write_text("dirty but unrelated")
            result = _run(
                ["merge", "--cwd", td, "--source", "feature-s", "--target", main]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-s"))


class TestMerge(unittest.TestCase):
    def test_full_chain_with_remote_merges_pushes_deletes(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-x", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            _bf.add_bare_remote(td)
            subprocess.run(
                ["git", "push", "-u", "origin", main],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = _run(
                ["merge", "--cwd", td, "--source", "feature-x", "--target", main]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-x", log.stdout)
            self.assertFalse(_bf.branch_exists(td, "feature-x"))
            remote_log = subprocess.run(
                ["git", "log", "origin/" + main, "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-x", remote_log.stdout)

    def test_no_remote_merges_and_deletes_without_push(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-y", "f.txt", "y", "feature y")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                ["merge", "--cwd", td, "--source", "feature-y", "--target", main]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-y", log.stdout)
            self.assertFalse(_bf.branch_exists(td, "feature-y"))

    def test_push_failure_leaves_source_branch_alive(self):
        # Load-bearing safety property: if the inner push fails, the
        # source branch must NOT be deleted — user retries after fixing
        # the remote. Reproduce by pointing origin at a bogus path
        # AFTER initial setup so the merge succeeds locally but the
        # subsequent `git push origin <target>` fails.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-z", "z.txt", "z", "feature z")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            _bf.add_bare_remote(td)
            subprocess.run(
                ["git", "push", "-u", "origin", main],
                cwd=td,
                capture_output=True,
                check=True,
            )
            # Sabotage the remote so the inner push fails.
            subprocess.run(
                ["git", "remote", "set-url", "origin", "/nonexistent/remote.git"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = _run(
                ["merge", "--cwd", td, "--source", "feature-z", "--target", main]
            )
            self.assertNotEqual(result.returncode, 0)
            # Merge happened locally...
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-z", log.stdout)
            # ...but feature-z must still exist — chain aborted before delete.
            self.assertTrue(
                _bf.branch_exists(td, "feature-z"),
                "source branch must survive a failed push",
            )

    def test_merge_failure_aborts_chain(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-a", "conflict.txt", "A", "A version")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            (Path(td) / "conflict.txt").write_text("MAIN")
            subprocess.run(
                ["git", "add", "conflict.txt"], cwd=td, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "main version"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )
            result = _run(
                ["merge", "--cwd", td, "--source", "feature-a", "--target", main]
            )
            self.assertNotEqual(result.returncode, 0)
            # feature-a must still exist — chain aborted before delete.
            self.assertTrue(
                _bf.branch_exists(td, "feature-a"),
                "source branch must survive a failed merge",
            )


class TestCloseReviewGate(unittest.TestCase):
    """close-review-gate counts code files in target...HEAD and emits the
    RUN_FULL_CODE_REVIEW threshold flag for the shared Step 4b."""

    def _run_gate(self, td: str) -> str:
        result = _run(["close-review-gate", "--cwd", td, "--target", "main"], cwd=td)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_two_code_files_runs_full_review(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _bf.make_commit(td, "feature", "a.py", "x = 1\n", "a")
            _bf.append_commit(td, "b.py")
            out = self._run_gate(td)
            self.assertIn("CLOSE_CODE_FILE_COUNT=2", out)
            self.assertIn("RUN_FULL_CODE_REVIEW=true", out)

    def test_one_code_file_below_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _bf.make_commit(td, "feature", "a.py", "x = 1\n", "a")
            out = self._run_gate(td)
            self.assertIn("CLOSE_CODE_FILE_COUNT=1", out)
            self.assertIn("RUN_FULL_CODE_REVIEW=false", out)

    def test_non_code_files_do_not_count(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _bf.make_commit(td, "feature", "README.md", "# doc\n", "docs")
            _bf.append_commit(td, "NOTES.md")
            out = self._run_gate(td)
            self.assertIn("CLOSE_CODE_FILE_COUNT=0", out)
            self.assertIn("RUN_FULL_CODE_REVIEW=false", out)

    def test_bad_target_fails_safe_to_false(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = _run(
                ["close-review-gate", "--cwd", td, "--target", "no-such-branch"],
                cwd=td,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RUN_FULL_CODE_REVIEW=false", result.stdout)


class TestDiffCommand(unittest.TestCase):
    """diff-command picks gh-pr-diff vs git-diff based on PR_OUTPUT shape.

    Each close skill (sprint, plan, free, story) used to inline a 3-line
    'Pick the diff command' stanza. This subcommand is the single source
    of truth — SKILL.md captures the printed command into a variable
    and passes it to the close-reviewer fork.
    """

    def test_numeric_pr_output_emits_gh_pr_diff(self):
        result = _run(["diff-command", "--pr-output", "4242", "--target", "main"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "gh pr diff 4242")

    def test_skipped_pr_output_emits_git_diff(self):
        result = _run(
            [
                "diff-command",
                "--pr-output",
                "skipped: gh not on PATH",
                "--target",
                "main",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff main...HEAD")

    def test_empty_pr_output_emits_git_diff(self):
        result = _run(["diff-command", "--pr-output", "", "--target", "main"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff main...HEAD")

    def test_target_branch_substituted_correctly(self):
        result = _run(
            [
                "diff-command",
                "--pr-output",
                "skipped: no gh",
                "--target",
                "develop",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff develop...HEAD")

    def test_non_numeric_arbitrary_text_treated_as_skipped(self):
        # Defensive: any non-numeric output (gh failure prose, leading
        # whitespace, etc.) falls through to git diff so the reviewer
        # never gets a malformed gh-pr-diff invocation.
        result = _run(
            [
                "diff-command",
                "--pr-output",
                "PR #42 created at https://...",
                "--target",
                "main",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff main...HEAD")


class TestHookPresent(unittest.TestCase):
    """`hook-present` reports whether the project runs tests via a git hook.

    Used by /xp-story-close and /xp-sprint-close preloads to drive a
    fallback prose nudge ("run the project's test command before
    confirming the merge") when no hook is wired up.

    Detection covers: default `.git/hooks/pre-commit` (executable, not
    `.sample`); `core.hooksPath` override pointing at a dir with an
    executable hook; framework markers (`.pre-commit-config.yaml`,
    `lefthook.yml/yaml`, `.husky/`).
    """

    def _make_executable(self, path: Path) -> None:
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)

    def test_executable_default_pre_commit_hook_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            self._make_executable(Path(td) / ".git" / "hooks" / "pre-commit")
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")

    def test_no_hook_and_no_markers_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "absent")

    def test_non_executable_pre_commit_hook_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            hook = Path(td) / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\nexit 0\n")
            # Don't chmod — file exists but isn't executable.
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "absent")

    def test_core_hookspath_override_with_executable_hook_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            override = Path(td) / "custom-hooks"
            override.mkdir()
            self._make_executable(override / "pre-commit")
            subprocess.run(
                ["git", "config", "core.hooksPath", str(override)],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")

    def test_tilde_in_core_hookspath_is_expanded(self):
        with tempfile.TemporaryDirectory() as home:
            hooks_under_home = Path(home) / "dotfiles" / "hooks"
            hooks_under_home.mkdir(parents=True)
            self._make_executable(hooks_under_home / "pre-commit")
            with tempfile.TemporaryDirectory() as td:
                _bf.init_repo(td)
                subprocess.run(
                    ["git", "config", "core.hooksPath", "~/dotfiles/hooks"],
                    cwd=td,
                    capture_output=True,
                    check=True,
                )
                env = {**_bf.GIT_ENV, "HOME": home}
                result = _run(["hook-present", "--cwd", td], env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "present")

    def test_executable_pre_push_hook_alone_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            self._make_executable(Path(td) / ".git" / "hooks" / "pre-push")
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")

    def test_pre_commit_framework_marker_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            (Path(td) / ".pre-commit-config.yaml").write_text("repos: []\n")
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")

    def test_lefthook_marker_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            (Path(td) / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n")
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")

    def test_husky_directory_marker_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            (Path(td) / ".husky").mkdir()
            (Path(td) / ".husky" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
            result = _run(["hook-present", "--cwd", td])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "present")


if __name__ == "__main__":
    unittest.main()
