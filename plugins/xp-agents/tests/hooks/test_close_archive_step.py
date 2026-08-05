#!/usr/bin/env python3
"""close_archive_step.absent_cause — naming why nothing was archived.

The step itself is exercised end-to-end through cmd_merge in
`test_close_common_archive.py`. What lives here is the cause-naming branch
alone: it has four outcomes, two of them (an unreadable `sprints/`, an SMM with
no archives at all) that a subprocess merge cannot reach without contorting the
fixture. Unit-level is where they are cheap and legible.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_archive_step


class TestAbsentCause(unittest.TestCase):
    def test_a_dir_with_no_events_log_reads_as_a_wrong_smm_dir(self):
        """`smm_preexisting` is the caller's probe, taken before any append.

        A false one means the directory carried no events.jsonl when the merge
        began, and an SMM always carries one — so the invocation named a
        directory that was never an SMM, and the close just ended with no
        snapshot at all. That has to be said out loud, not folded into the
        benign reading.
        """
        with tempfile.TemporaryDirectory() as td:
            cause = close_archive_step.absent_cause(Path(td), False)
        self.assertIn("not an SMM directory", cause)
        self.assertIn("--smm-dir", cause)

    def test_a_real_smm_with_no_archives_says_none_was_ever_written(self):
        with tempfile.TemporaryDirectory() as td:
            cause = close_archive_step.absent_cause(Path(td), True)
        self.assertIn("no sprint was ever written", cause)
        self.assertNotIn("already archived", cause)

    def test_a_prior_archive_is_reported_as_evidence_not_as_proof(self):
        """Every past sprint leaves an archive behind, so "an archive exists"
        cannot prove THIS close's retry archived it — pointing at another
        project's real SMM looks identical from here. The message must name the
        file it found and leave the reading to the operator, or a close that
        produced no snapshot reads as a benign duplicate."""
        with tempfile.TemporaryDirectory() as td:
            sprints = Path(td) / "sprints"
            sprints.mkdir()
            (sprints / "sprint_20260101T000000.json").write_text("{}")
            cause = close_archive_step.absent_cause(Path(td), True)
        self.assertIn("already archived", cause)
        self.assertIn(
            "sprint_20260101T000000.json",
            cause,
            "the archive it found must be named — an unnamed claim gives the "
            "reader nothing to check it against",
        )
        self.assertIn("otherwise no sprint was written", cause)

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root ignores directory permissions, so the read cannot be made to fail",
    )
    def test_an_unreadable_sprints_dir_is_never_reported_as_an_empty_one(self):
        """The silent-empty trap `sprint_archive.newest_path` exists to stop.

        A `glob` here would swallow the PermissionError and report "no sprint
        was ever written here" for a directory nobody could read — the strongest
        possible statement made from the least possible evidence.
        """
        with tempfile.TemporaryDirectory() as td:
            sprints = Path(td) / "sprints"
            sprints.mkdir()
            (sprints / "sprint_20260101T000000.json").write_text("{}")
            sprints.chmod(0o000)
            try:
                cause = close_archive_step.absent_cause(Path(td), True)
            finally:
                sprints.chmod(0o755)
        self.assertIn("cannot tell", cause)
        self.assertNotIn("no sprint was ever written", cause)


if __name__ == "__main__":
    unittest.main()
