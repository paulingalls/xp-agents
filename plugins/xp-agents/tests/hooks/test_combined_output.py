#!/usr/bin/env python3
"""Behavioral tests for branch_lifecycle.combined_output.

A failed `git push` reports its own error on stderr while a pre-push hook's
output — usually the actual cause — goes to stdout. `combined_output` is the
one place in the repo that keeps both streams; these tests lock in that
contract.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import branch_lifecycle


class TestCombinedOutput(unittest.TestCase):
    def test_both_streams_present_stderr_first(self):
        r = subprocess.CompletedProcess([], 1, stdout="out-part", stderr="err-part")
        self.assertEqual(branch_lifecycle.combined_output(r), "err-partout-part")

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
