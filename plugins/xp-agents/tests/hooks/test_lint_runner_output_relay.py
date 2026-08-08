#!/usr/bin/env python3
"""Two of the three lint_runners.py sites that used to pick ONE stream
(stdout-first) must relay BOTH, stderr-first — the same convention
`branch_lifecycle.combined_output` already enforces for the git-subprocess
call sites (see test_combined_output.py). A linter that reports its real
diagnosis on the stream these functions used to discard lost that diagnosis
silently. The third (bytes-typed) site, run_linter_stdin, gets its own
proofs added alongside its own fix.

Split into its own module rather than folding these into
test_lint_ruff_and_batch.py / test_lint_config_style_flags.py: those files
own the retry/timeout/classification behaviour of each function, and this
file owns exactly one cross-cutting property — stream relay — across all
three sites.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lint_runners


class TestRunLinterRelaysBothStreams(unittest.TestCase):
    """run_linter (edit-time, single file) used to report `stdout or stderr` —
    stdout picked whenever it was non-empty, stderr silently dropped."""

    def test_discarded_stderr_reaches_the_report(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {
                    "returncode": 1,
                    "stdout": "noise-on-stdout",
                    "stderr": "diagnosis-on-stderr",
                },
            )()
            output = lint_runners.run_linter("ruff", "a.py", cwd="/tmp")

        assert output is not None
        self.assertIn("diagnosis-on-stderr", output)
        self.assertIn("noise-on-stdout", output)

    def test_stderr_comes_first(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {"returncode": 1, "stdout": "on-stdout", "stderr": "on-stderr"},
            )()
            output = lint_runners.run_linter("ruff", "a.py", cwd="/tmp")

        assert output is not None
        self.assertLess(output.index("on-stderr"), output.index("on-stdout"))


class TestRunLinterBatchRelaysBothStreams(unittest.TestCase):
    """run_linter_batch (the commit gate's fork-over-many-paths runner) used
    to report `stdout or stderr` — same discard, at the commit gate itself."""

    def test_discarded_stderr_reaches_the_report(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {
                    "returncode": 1,
                    "stdout": "noise-on-stdout",
                    "stderr": "diagnosis-on-stderr",
                },
            )()
            run = lint_runners.run_linter_batch("ruff", ["a.py"], cwd="/tmp")

        self.assertEqual(run.status, "findings")
        self.assertIn("diagnosis-on-stderr", run.output)
        self.assertIn("noise-on-stdout", run.output)

    def test_stderr_comes_first(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {"returncode": 1, "stdout": "on-stdout", "stderr": "on-stderr"},
            )()
            run = lint_runners.run_linter_batch("ruff", ["a.py"], cwd="/tmp")

        self.assertLess(run.output.index("on-stderr"), run.output.index("on-stdout"))

    def test_whitespace_only_stdout_no_longer_masks_stderr_as_unverified(self):
        """The classification this story's fix moves: a stdout that is
        non-empty but strips to nothing used to be picked over a stderr that
        had a real diagnosis (`stdout or stderr` — a non-empty string is
        truthy even when it's all whitespace), and the run reported
        UNVERIFIED despite the linter having said exactly why it failed.
        Combining both streams means that diagnosis is never discarded."""
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {"returncode": 1, "stdout": "   \n", "stderr": "real diagnosis"},
            )()
            run = lint_runners.run_linter_batch("ruff", ["a.py"], cwd="/tmp")

        self.assertEqual(run.status, "findings")
        self.assertIn("real diagnosis", run.output)


class TestRunLinterStdinRelaysBothStreams(unittest.TestCase):
    """run_linter_stdin (the divergent-index path, binary mode) used to report
    `stdout or stderr` in bytes — same discard, one decode step later."""

    def test_discarded_stderr_reaches_the_report(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {
                    "returncode": 1,
                    "stdout": b"noise-on-stdout",
                    "stderr": b"diagnosis-on-stderr",
                },
            )()
            run = lint_runners.run_linter_stdin(
                "ruff", "app.py", b"x = 1\n", cwd="/tmp"
            )

        self.assertEqual(run.status, "findings")
        self.assertIn("diagnosis-on-stderr", run.output)
        self.assertIn("noise-on-stdout", run.output)

    def test_stderr_comes_first(self):
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {"returncode": 1, "stdout": b"on-stdout", "stderr": b"on-stderr"},
            )()
            run = lint_runners.run_linter_stdin(
                "ruff", "app.py", b"x = 1\n", cwd="/tmp"
            )

        self.assertLess(run.output.index("on-stderr"), run.output.index("on-stdout"))

    def test_whitespace_only_stdout_no_longer_masks_stderr_as_unverified(self):
        """The bytes-typed twin of the batch-path classification pin above."""
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {"returncode": 1, "stdout": b"   \n", "stderr": b"real diagnosis"},
            )()
            run = lint_runners.run_linter_stdin(
                "ruff", "app.py", b"x = 1\n", cwd="/tmp"
            )

        self.assertEqual(run.status, "findings")
        self.assertIn("real diagnosis", run.output)

    def test_both_streams_survive_the_decode_leniently(self):
        """A bad byte on either stream must not raise — the linter's own
        output echoes the source line it flagged, so it is no more guaranteed
        to be UTF-8 than the staged blob is."""
        with (
            patch("lint_runners.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_runners.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type(
                "R",
                (),
                {
                    "returncode": 1,
                    "stdout": b"stdout \xff oops\n",
                    "stderr": b"stderr \xff oops\n",
                },
            )()
            run = lint_runners.run_linter_stdin(
                "ruff", "app.py", b"x = 1\n", cwd="/tmp"
            )

        self.assertEqual(run.status, "findings")
        self.assertIn("stdout", run.output)
        self.assertIn("stderr", run.output)


if __name__ == "__main__":
    unittest.main()
