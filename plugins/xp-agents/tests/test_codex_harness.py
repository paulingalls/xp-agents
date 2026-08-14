#!/usr/bin/env python3
"""Tests for the shared harness plumbing in `_codex_harness`.

The plumbing has three consumers and no coverage of its own, which is how a
diagnostic defect in it stayed invisible: when the inner run could not START,
the assertion reported an empty string, so CI printed a bare `1 != 0` and named
neither the cause nor the fix.
"""

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _codex_harness import assert_module_skips_without_harness


class _GatedRow:
    """Stands in for a consumer's harness-gated class.

    Deliberately NOT a `TestCase`: the helper only asks the loader to count the
    `test_*` names on it, and a real TestCase here would be collected and run as
    a row of this suite, which it is not.
    """

    def test_placeholder(self) -> None:
        pass


class TestTheFailureDiagnosticCarriesStderr(unittest.TestCase):
    """An inner run that cannot start explains itself on stderr, not stdout.

    This is the exact shape of the CI break: an interpreter with no importable
    pytest exits 1, writes `No module named pytest` to stderr, and leaves stdout
    EMPTY. Reporting stdout alone therefore reduced the failure to `1 != 0` with
    nothing after the colon — true, and useless. Asserting on the message rather
    than on the return code is deliberate: the return code was already correct.
    """

    def test_a_stderr_only_inner_failure_names_its_cause(self) -> None:
        dead = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="No module named pytest\n"
        )

        self.assertIn("No module named pytest", self._message_for(dead))

    def test_both_streams_reach_the_message_stderr_last(self) -> None:
        """Neither stream alone is enough, and the order is not incidental.

        Asserting only the stderr half would stay green against a regression
        that narrowed the report to `result.stderr` — and stdout is where an
        inner run that STARTED and then failed explains itself, which is the
        common case, not the one that broke CI. The index comparison pins the
        ordering the truncation depends on: `[-2000:]` keeps the tail, so
        stderr must come last to survive a large stdout.
        """
        both = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="1 failed, 2 passed\n",
            stderr="the inner run also complained\n",
        )

        message = self._message_for(both)

        self.assertIn("1 failed, 2 passed", message)
        self.assertIn("the inner run also complained", message)
        self.assertLess(
            message.index("1 failed, 2 passed"),
            message.index("the inner run also complained"),
        )

    def _message_for(self, completed: subprocess.CompletedProcess) -> str:
        """The AssertionError text the helper raises for *completed*."""
        with (
            mock.patch.object(subprocess, "run", return_value=completed),
            self.assertRaises(AssertionError) as raised,
        ):
            assert_module_skips_without_harness(
                self,
                module_path=Path(__file__),
                gated_classes=(_GatedRow,),
            )
        return str(raised.exception)


if __name__ == "__main__":
    unittest.main()
