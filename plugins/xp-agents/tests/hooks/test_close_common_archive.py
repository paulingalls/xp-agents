#!/usr/bin/env python3
"""close_common.py `merge --archive-sprint` — folding the archive into the merge.

Split from `test_close_common_pipeline.py` (798 lines). The archive step sits at
one specific point in the merge chain, and the reason is subtle enough that
these tests are almost all about placement and failure recovery rather than
about archiving — see the suite docstring below. Grouped away from the rest of
the merge chain in `test_close_common_merge.py` for that reason.
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


class TestMergeArchiveSprint(unittest.TestCase):
    """--archive-sprint (story-002, SMM debt 80ea48e4d5fb): folds the sprint
    archive into cmd_merge, after the merge commit AND the target push but
    BEFORE delete_branch — the one irreversible step. An archive failure
    returns nonzero with the source branch intact, so re-running the identical
    merge command is safe: the re-merge is idempotent ("Already up to date"),
    the re-push is a no-op, and the archive retries.

    The archive is LAST-but-one deliberately. sprint.json is the acceptance
    verify-gate's only input (close_verify_gate fails open when it is gone), so
    archiving it while a later step can still fail would disarm that gate for
    every subsequent run. Nothing archives until the close is complete enough
    that only the branch delete remains."""

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

    def test_push_failure_leaves_sprint_json_for_the_retry(self):
        # A failed target push must leave sprint.json IN PLACE. Archiving it
        # first would hand the retry an SMM with no sprint, and the acceptance
        # verify-gate fails open on a missing sprint — so a close that is not
        # finished would have silently disarmed its own deterministic backstop.
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
            # Sabotage the remote so the merge succeeds locally but the
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
            self.assertTrue(
                (smm / "sprint.json").exists(),
                "sprint.json must survive a failed push — it is the acceptance "
                "gate's only input, and the close is not complete",
            )
            self.assertEqual(list((smm / "sprints").glob("sprint_*.json")), [])

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
            self.assertFalse((smm / "sprint.json").exists())
            archived_after = list((smm / "sprints").glob("sprint_*.json"))
            self.assertEqual(len(archived_after), 1)

    def test_absent_sprint_json_says_so_on_stderr_and_completes_chain(self):
        # The idempotent branch: nothing to archive. It must NOT be a silent
        # stdout aside — a genuinely missing sprint.json (wrong --smm-dir, a
        # sprint that was never written) has to be visible, since the close
        # otherwise exits 0 having produced no snapshot at all. It still does
        # not abort: the merge and push already landed, and no retry can make
        # an absent file appear.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            smm = self._make_smm(td)
            _bf.make_commit(td, "feature-nosprint", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = _run(
                [
                    "merge",
                    "--cwd",
                    td,
                    "--source",
                    "feature-nosprint",
                    "--target",
                    main,
                    "--archive-sprint",
                    "--smm-dir",
                    str(smm),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no sprint.json", result.stderr)
            self.assertFalse(_bf.branch_exists(td, "feature-nosprint"))

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

    def test_verify_gate_acceptance_stays_armed_across_a_failed_push(self):
        # Pins the production combination sprint-close actually runs: `merge
        # --verify-gate acceptance --archive-sprint`. The acceptance gate fails
        # OPEN on a missing sprint.json (close_verify_gate.py), so an archive
        # that ran before the close finished would leave every retry ungated.
        # Ordering the archive after the push keeps the gate's input alive for
        # exactly as long as a step can still fail.
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
            self.assertTrue(
                (smm / "sprint.json").exists(),
                "the retry's acceptance gate must still have a sprint to read",
            )

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
