#!/usr/bin/env python3
"""close_common.py `merge` — the chain, and the backstop that guards it.

Split from `test_close_common_pipeline.py` (798 lines). The merge chain is the
irreversible half of the pipeline: it commits the merge, pushes the target, and
deletes the source branch. Every test here is about the ORDER of those steps and
what survives when one of them fails, which is why they group away from the
preflight/push/create-pr commands that precede them.

The `--archive-sprint` leg has its own suite in `test_close_common_archive.py`;
the read-only review-support commands are in
`test_close_common_review_support.py`.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import _branching_fixtures as _bf
from _close_common_runner import _run


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


if __name__ == "__main__":
    unittest.main()
