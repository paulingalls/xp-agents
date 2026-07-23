#!/usr/bin/env python3
"""Tests for scripts/close_common.py — preflight/push/create-pr/merge pipeline.

Split from test_close_common.py by test-class grouping: this file covers the
git-mutating pipeline commands the close skills invoke in sequence — the
preflight guard, push, create-pr, and the merge chain (including the
--review-clean-cwd backstop). See test_close_common_review_support.py for the
read-only review-support commands (close-review-gate, diff-command,
hook-present).

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


class TestMergeArchiveSprint(unittest.TestCase):
    """--archive-sprint (story-002, SMM debt 80ea48e4d5fb): folds the sprint
    archive into cmd_merge, AFTER the merge commit but BEFORE delete_branch —
    the one irreversible step. An archive failure returns nonzero with the
    source branch intact, so re-running the identical merge command is safe:
    the re-merge is idempotent ("Already up to date") and the archive retries."""

    def _make_smm(self, td: str) -> Path:
        smm = Path(td) / "smm"
        smm.mkdir()
        (smm / "events.jsonl").touch()
        (smm / "events.lock").touch()
        return smm

    def test_archive_failure_keeps_source_branch_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.write_sprint_json(smm, "sprint-001", "goal")
            # Sabotage sprint_archive.archive: a FILE sits where it needs a dir,
            # so Path.mkdir(exist_ok=True) raises FileExistsError (an OSError) —
            # a real failure, not a monkeypatch, so it exercises the actual
            # subprocess-invoked cmd_merge exactly as production would hit it.
            (smm / "sprints").write_text("not a directory")
            _bf.make_commit(td, "feature-arc", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-arc",
                    "--target",
                    main,
                    "--archive-sprint",
                    "--smm-dir",
                    str(smm),
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-arc", log.stdout)
            self.assertTrue(
                _bf.branch_exists(td, "feature-arc"),
                "source branch must survive a failed archive so a retry can "
                "re-merge idempotently",
            )
            # Archive raised before shutil.move — sprint.json untouched.
            self.assertTrue((smm / "sprint.json").exists())

    def test_idempotent_double_archive_archives_once(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.write_sprint_json(smm, "sprint-001", "goal")
            _bf.make_commit(td, "feature-idem", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            bare = _bf.add_bare_remote(td)
            subprocess.run(
                ["git", "push", "-u", "origin", main],
                cwd=td,
                capture_output=True,
                check=True,
            )
            # Sabotage the remote so the merge succeeds + archives, but the
            # subsequent target push fails — source branch survives for retry.
            subprocess.run(
                ["git", "remote", "set-url", "origin", "/nonexistent/remote.git"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            merge_args = [
                "merge",
                "--cwd",
                td,
                "--source",
                "feature-idem",
                "--target",
                main,
                "--archive-sprint",
                "--smm-dir",
                str(smm),
            ]
            first = _run(merge_args)
            self.assertNotEqual(first.returncode, 0)
            self.assertTrue(_bf.branch_exists(td, "feature-idem"))
            self.assertFalse((smm / "sprint.json").exists())
            archived = list((smm / "sprints").glob("sprint_*.json"))
            self.assertEqual(len(archived), 1)

            # Restore the remote and retry the identical command.
            subprocess.run(
                ["git", "remote", "set-url", "origin", bare],
                cwd=td,
                capture_output=True,
                check=True,
            )
            second = _run(merge_args)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-idem"))
            archived_after = list((smm / "sprints").glob("sprint_*.json"))
            self.assertEqual(
                len(archived_after),
                1,
                "archive must not run again once sprint.json is gone",
            )

    def test_happy_path_archives_and_completes_full_chain(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.write_sprint_json(smm, "sprint-001", "goal")
            _bf.make_commit(td, "feature-happy", "f.txt", "x", "feature commit")
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
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-happy",
                    "--target",
                    main,
                    "--archive-sprint",
                    "--smm-dir",
                    str(smm),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("archived sprint:", result.stdout)
            self.assertFalse((smm / "sprint.json").exists())
            archived = list((smm / "sprints").glob("sprint_*.json"))
            self.assertEqual(len(archived), 1)
            self.assertFalse(_bf.branch_exists(td, "feature-happy"))
            remote_log = subprocess.run(
                ["git", "log", "origin/" + main, "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("feature-happy", remote_log.stdout)

    def test_without_flag_never_archives(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.write_sprint_json(smm, "sprint-001", "goal")
            _bf.make_commit(td, "feature-off", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-off",
                    "--target",
                    main,
                    "--smm-dir",
                    str(smm),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("archived", result.stdout.lower())
            self.assertTrue((smm / "sprint.json").exists())
            self.assertFalse(_bf.branch_exists(td, "feature-off"))

    def test_flag_without_smm_dir_refuses_and_keeps_source(self):
        # A misconfigured invocation (--archive-sprint with no --smm-dir) must
        # not silently skip the archive — it fails the same way an archive
        # failure would: nonzero, source intact, no push/delete.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "feature-noargs", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-noargs",
                    "--target",
                    main,
                    "--archive-sprint",
                ]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--smm-dir", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "feature-noargs"))

    def test_verify_gate_acceptance_retry_after_archive_survives_fail_open(self):
        # Pins the production combination sprint-close actually runs: `merge
        # --verify-gate acceptance --archive-sprint`. Hazard #3 from the story:
        # after a successful archive but a later failed step, sprint.json is
        # already gone, so the RETRY's verify-gate re-load of sprint.json
        # returns None and close_verify_gate.verify_gate_block fails OPEN
        # (close_verify_gate.py) — the retry is not blocked, the re-merge is a
        # no-op, and archive() is idempotent (returns None). If a future change
        # made the acceptance gate fail CLOSED on a missing sprint, this test
        # would catch the regression by going red.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.write_sprint_json(smm, "sprint-001", "goal")
            _bf.make_commit(td, "feature-gated", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            bare = _bf.add_bare_remote(td)
            subprocess.run(
                ["git", "push", "-u", "origin", main],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "remote", "set-url", "origin", "/nonexistent/remote.git"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            merge_args = [
                "merge",
                "--cwd",
                td,
                "--source",
                "feature-gated",
                "--target",
                main,
                "--verify-gate",
                "acceptance",
                "--archive-sprint",
                "--smm-dir",
                str(smm),
            ]
            first = _run(merge_args)
            self.assertNotEqual(first.returncode, 0)
            self.assertTrue(_bf.branch_exists(td, "feature-gated"))
            self.assertFalse((smm / "sprint.json").exists())

            subprocess.run(
                ["git", "remote", "set-url", "origin", bare],
                cwd=td,
                capture_output=True,
                check=True,
            )
            second = _run(merge_args)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-gated"))
            archived_after = list((smm / "sprints").glob("sprint_*.json"))
            self.assertEqual(len(archived_after), 1)


if __name__ == "__main__":
    unittest.main()
