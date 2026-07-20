#!/usr/bin/env python3
"""Tests for scripts/close_common.py — review-support commands.

Split from test_close_common.py by test-class grouping: this file covers the
read-only commands the close skills use to drive the review step —
close-review-gate (sizing threshold for the full /code-review), diff-command
(the merged-range diff the reviewer must review), and hook-present (detects a
project test-running git hook). See test_close_common_pipeline.py for the
git-mutating preflight/push/create-pr/merge pipeline.

Tests are subprocess-based: they invoke close_common.py as a script
against a hermetic temp git repo.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import _branching_fixtures as _bf
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
