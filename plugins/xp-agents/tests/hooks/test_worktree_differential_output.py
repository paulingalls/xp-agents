#!/usr/bin/env python3
"""What `worktree_differential` RELAYS from each leg — both streams, stderr
first, each tailed before the join.

Split out of test_worktree_differential.py, which owns the measurement itself
(refusal, gap/no-gap, throwaway removal). These pin one cross-cutting property
of the reported OUTPUT, on both the completed and the timed-out branch, and the
two groups grow for unrelated reasons.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import worktree_differential
from test_worktree_differential import _DifferentialTestCase


class TestBothStreamsRelayedInOutput(_DifferentialTestCase):
    """`worktree_output`/`primary_output` used to report `stderr or stdout` —
    whichever stream the `or` happened to pick, the other was silently
    dropped. Same command on both legs (OUTCOME_NO_GAP) so this pins the
    relay itself, independent of the gap/no-gap question `TestTwoLegCompare`
    already owns."""

    _CMD = "sh -c 'echo diagnosis-on-stdout && echo noise-on-stderr >&2 && false'"

    def test_both_streams_reach_the_report(self) -> None:
        result = self.run_differential(self._CMD)

        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_NO_GAP)
        for key in ("primary_output", "worktree_output"):
            self.assertIn("diagnosis-on-stdout", result[key], key)
            self.assertIn("noise-on-stderr", result[key], key)

    def test_stderr_comes_first(self) -> None:
        result = self.run_differential(self._CMD)

        for key in ("primary_output", "worktree_output"):
            output = result[key]
            self.assertLess(
                output.index("noise-on-stderr"),
                output.index("diagnosis-on-stdout"),
                key,
            )


class TestTailDoesNotEvictTheOtherStream(_DifferentialTestCase):
    """The tail truncation the relay also touches: combining the streams must
    not let a verbose stdout evict the stderr diagnosis from the kept slice —
    each stream is tailed to `_OUTPUT_TAIL_CHARS` independently before the
    join, rather than the joined string being tailed."""

    # Longer than _OUTPUT_TAIL_CHARS (4000): a naive tail-the-joined-string
    # implementation would let this evict the short stderr diagnosis.
    _CMD = "sh -c 'echo diagnosis-on-stderr >&2 && printf %04500d 1 && false'"

    def test_stderr_diagnosis_survives_a_chatty_stdout(self) -> None:
        result = self.run_differential(self._CMD)

        for key in ("primary_output", "worktree_output"):
            self.assertIn("diagnosis-on-stderr", result[key], key)


class TestTailedStreamsDoNotRunTogether(unittest.TestCase):
    """`_tail` strips, so the newline that separated the two streams is gone by
    the time they are joined — without one put back, the last stderr line and
    the first stdout line read as one line."""

    def test_a_newline_separates_the_two_tails(self) -> None:
        joined = worktree_differential._tail_streams("error: no such ref\n", "out\n")

        self.assertEqual(joined, "error: no such ref\nout")


class TestTimedOutLegRelaysBothStreams(_DifferentialTestCase):
    """The branch where the relay matters MOST: a hung leg has no exit code to
    compare, so whatever it said before the kill is the whole diagnosis — and
    that branch picked stdout, dropping stderr."""

    def test_both_streams_reach_the_timeout_report(self) -> None:
        result = self.run_differential(
            "sh -c 'echo diagnosis-on-stderr >&2 && echo noise-on-stdout && sleep 30'",
            timeout=1,
        )

        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_ERROR)
        self.assertIn("diagnosis-on-stderr", result["primary_output"])
        self.assertIn("noise-on-stdout", result["primary_output"])


if __name__ == "__main__":
    unittest.main()
