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
            # The remedy must stage NEW files: a plain `commit -am` cannot add
            # the untracked reviewer-fix.txt, so the message names `add -A`.
            self.assertIn("add -A", result.stderr)
            # Merge did NOT happen — source branch survives for a retry.
            self.assertTrue(_bf.branch_exists(td, "feature-r"))

    def test_invalid_review_cwd_skips_check(self):
        # A --review-clean-cwd that isn't a git worktree (misdetected/removed
        # path) has no reviewer fix to protect; a misleading un-clearable
        # refusal would be worse than skipping — the merge must proceed.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-i", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            with tempfile.TemporaryDirectory() as non_repo:
                result = _run(
                    [
                        "merge",
                        "--cwd",
                        td,
                        "--source",
                        "feature-i",
                        "--target",
                        main,
                        "--review-clean-cwd",
                        non_repo,
                    ]
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-i"))

    def test_missing_review_cwd_skips_check(self):
        # A --review-clean-cwd path that no longer exists must not crash the
        # merge (subprocess would raise on a missing cwd) — treat as no worktree
        # to protect and proceed.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-m", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            missing = str(Path(td) / "gone")
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-m",
                    "--target",
                    main,
                    "--review-clean-cwd",
                    missing,
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-m"))

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
    """diff-command emits the merged range `git diff <target>...<source>`.

    The close-reviewer must review the exact ref the merge lands. cmd_merge
    merges a LOCAL ref (`<source>`); the PR head is the REMOTE head as of
    Step 2's push and misses close-time fixes (Step 4b validate-and-fix,
    Step 5c "fix now") that land AFTER the push and still ship in the merge —
    live at sprint-118, where the reviewer read the pushed commit while all
    five of its own defect fixes sat unpushed. So the review INPUT is
    `<source>`: never the PR head, and never `HEAD` (at story-close the
    reviewer runs from the ORCHESTRATOR checkout, where HEAD is the sprint
    branch, not the story branch). Three-dot matches the sizing gate
    (commits.get_code_files_in_range).

    Subprocess-based: `_run` invokes close_common.py as a script and asserts
    on `result.stdout.strip()`.
    """

    def test_emits_merged_range_even_when_pr_created(self):
        # AC1: even when create-pr returned a numeric PR number, the review
        # INPUT is the merged-ref range — never `gh pr diff <N>` (the PR head).
        result = _run(["diff-command", "--target", "main", "--source", "feature-x"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff main...feature-x")
        self.assertNotIn("gh pr diff", result.stdout)

    def test_never_emits_gh_pr_diff(self):
        # Pin: no target/source combination ever produces a gh-pr-diff form —
        # even a source that LOOKS numeric is still a ref, not a PR number.
        for target, source in (
            ("main", "feature-x"),
            ("develop", "story-042"),
            ("release", "4242"),
        ):
            result = _run(["diff-command", "--target", target, "--source", source])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("gh pr diff", result.stdout)
            self.assertEqual(result.stdout.strip(), f"git diff {target}...{source}")

    def test_range_names_source_not_head(self):
        # AC2: the range names <source>, NOT HEAD. At story-close the reviewer
        # runs from the orchestrator checkout whose HEAD is the sprint branch;
        # `...HEAD` would review the wrong tree. Naming <source> is cwd-independent
        # (worktrees share the object store and refs).
        result = _run(["diff-command", "--target", "main", "--source", "story-042"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "git diff main...story-042")
        self.assertNotIn("HEAD", result.stdout)

    def test_source_is_required(self):
        # --source is required: without it argparse must fail, so a caller that
        # forgets to name the merged ref never silently emits a malformed range.
        result = _run(["diff-command", "--target", "main"])
        self.assertNotEqual(result.returncode, 0)

    def test_e2e_post_push_fix_appears_in_emitted_diff(self):
        # AC3/AC5: a fix committed on <source> AFTER the PR push appears in the
        # generated-AND-executed diff — the falsifiable proof reviewed==merged.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            # The story commit the PR push captured (remote head as of Step 2).
            _bf.make_commit(td, "feature-x", "orig.txt", "original\n", "story work")
            # A close-time fix committed AFTER the push, on the source branch —
            # invisible to `gh pr diff <N>`, visible to the merged range.
            (Path(td) / "reviewer_fix.txt").write_text("POST_PUSH_FIX\n")
            subprocess.run(
                ["git", "add", "reviewer_fix.txt"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "close-time reviewer fix"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )
            result = _run(["diff-command", "--target", "main", "--source", "feature-x"])
            self.assertEqual(result.returncode, 0, result.stderr)
            emitted = result.stdout.strip()
            self.assertEqual(emitted, "git diff main...feature-x")
            executed = subprocess.run(
                emitted.split(),
                cwd=td,
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertIn("POST_PUSH_FIX", executed.stdout)


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
