#!/usr/bin/env python3
"""Behavioral tests for branch_lifecycle.combine_streams/combined_output.

A failed `git push` reports its own error on stderr while a pre-push hook's
output — usually the actual cause — goes to stdout. `combine_streams` is the
one place in the repo that spells the stderr-first join; every subprocess relay
routes through it, and `combined_output` is its `CompletedProcess` wrapper.
These tests lock in that contract.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import branch_lifecycle


class TestCombineStreams(unittest.TestCase):
    """The pair-taking primitive, for the relays that hold no CompletedProcess:
    bytes decoded per-stream, streams tailed before the join, or the two streams
    recovered off a killed child's TimeoutExpired."""

    def test_stderr_comes_first(self):
        joined = branch_lifecycle.combine_streams("err-part\n", "out-part")
        self.assertEqual(joined, "err-part\nout-part")

    def test_a_stderr_without_its_newline_does_not_run_into_stdout(self):
        """Callers that strip or tail the streams first lose the newline that
        made a raw concatenation readable, and `error: no such ref` would run
        straight into stdout's first line."""
        joined = branch_lifecycle.combine_streams("error: no such ref", "hook output")
        self.assertEqual(joined, "error: no such ref\nhook output")

    def test_no_separator_is_invented_when_one_stream_is_empty(self):
        self.assertEqual(branch_lifecycle.combine_streams("err", ""), "err")
        self.assertEqual(branch_lifecycle.combine_streams("", "out"), "out")


class TestCombinedOutput(unittest.TestCase):
    def test_both_streams_present_stderr_first(self):
        r = subprocess.CompletedProcess([], 1, stdout="out-part", stderr="err-part\n")
        self.assertEqual(branch_lifecycle.combined_output(r), "err-part\nout-part")

    def test_empty_stderr_populated_stdout_is_returned(self):
        # The bug this story exists to fix: a hook that writes only to stdout.
        r = subprocess.CompletedProcess([], 1, stdout="hook said: cause", stderr="")
        self.assertEqual(branch_lifecycle.combined_output(r), "hook said: cause")

    def test_both_empty_returns_empty_string_no_crash_on_none(self):
        r = subprocess.CompletedProcess([], 1, stdout=None, stderr=None)
        self.assertEqual(branch_lifecycle.combined_output(r), "")

    def test_result_is_unstripped(self):
        r = subprocess.CompletedProcess([], 1, stdout="out\n", stderr="")
        self.assertEqual(branch_lifecycle.combined_output(r), "out\n")


class TestTailStreams(unittest.TestCase):
    """The bounded relay. A red pre-push hook now runs the whole suite, so an
    unbounded relay hands the reader hundreds of KB and buries git's own line."""

    def test_each_stream_is_tailed_independently(self):
        """After the join, a long stdout would evict the stderr that goes
        first — which is the half naming what actually failed."""
        joined = branch_lifecycle.tail_streams("e" * 50, "o" * 50, 10)

        self.assertTrue(joined.startswith("..." + "e" * 10))
        self.assertTrue(joined.endswith("..." + "o" * 10))

    def test_short_streams_are_untouched_and_unmarked(self):
        self.assertEqual(branch_lifecycle.tail_streams("err", "out", 10), "err\nout")

    def test_tailed_output_bounds_a_completed_process(self):
        r = subprocess.CompletedProcess([], 1, stdout="o" * 99999, stderr="err")
        tailed = branch_lifecycle.tailed_output(r)

        self.assertIn("err", tailed)
        self.assertLess(len(tailed), 99999)


class TestPushSourceNoVerifyRelaysBothStreams(unittest.TestCase):
    """push_source_no_verify must warn with BOTH streams, not stderr alone —
    a stdout-only hook cause must reach the warning."""

    def test_stdout_only_cause_reaches_the_warning(self):
        def fake_run(*a, **k):
            return subprocess.CompletedProcess(a[0], 1, "hook said: cause", "")

        with patch.object(branch_lifecycle.subprocess, "run", fake_run):
            buf = []
            with patch.object(sys.stderr, "write", lambda s: buf.append(s)):
                branch_lifecycle.push_source_no_verify("/repo", "story-src")

        self.assertIn("cause", "".join(buf))


if __name__ == "__main__":
    unittest.main()
