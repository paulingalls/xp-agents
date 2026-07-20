#!/usr/bin/env python3
"""Tests for bash_post_tool's post-test-run nudges: commit-after-green
nudge, the TDD red-phase regression-concern gate, and the (removed)
push-triggered session-end nudge.

Split from test_bash_commit.py to stay under the file-size cap; see that
file's docstring for the sibling map.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
)


class TestBashPostToolGreenNudge(_HookTestCase):
    """Tests for commit-after-green nudge in bash_post_tool."""

    def test_green_with_uncommitted_code_returns_nudge(self):
        """All tests pass + uncommitted code files -> nudge string returned."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("commit", result.lower())

    def test_green_no_uncommitted_code_no_nudge(self):
        """All tests pass but no uncommitted code files -> no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=[]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_green_after_failure_confirms_resolution(self):
        """Tests pass after prior failure -> context confirms resolution."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 3 failed",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)

        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("prior test failures resolved", result.lower())
        self.assertIn("commit", result.lower())

    def test_red_no_nudge(self):
        """Failing tests -> no nudge (even with uncommitted code)."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 3 passed, 2 failed in 1.2s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_xp_agent_no_nudge(self):
        """xp- agents never get the nudge (recursion guard)."""
        result = bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
                agent_type="code-review",
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_zero_passed_zero_failed_no_nudge(self):
        """Ambiguous output (0 passed, 0 failed) -> no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="no tests ran",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)


class TestBashPostToolTddRedConcernGate(_HookTestCase):
    """AC1/AC2/AC4 (story-018): the severity=high regression concern is
    gated on tdd_red — a deliberate red step (test-only-dirty working
    tree) must not be flagged as a regression, but an honest failure with
    no test-layer edits pending still is. test_run_complete also carries
    suite size so a scoped run is distinguishable from a full run."""

    def test_deliberate_red_step_suppresses_regression_concern(self):
        """AC1: uncommitted test file, no impl code in flight, failed>0."""
        with (
            patch("commits.get_uncommitted_files", return_value=["tests/test_x.py"]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="pytest",
                    stdout="===== 1 passed, 1 failed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        concerns = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(concerns, [])

    def test_non_red_failure_still_appends_concern(self):
        """AC2: failure with no test-layer edits pending is a real regression."""
        with (
            patch("commits.get_uncommitted_files", return_value=["src/app.py"]),
            patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="pytest",
                    stdout="===== 1 passed, 1 failed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        concerns = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0].get("severity"), "high")

    def test_deliberate_red_step_status_event_still_records_failure(self):
        """Suppressing the concern must not hide the failure itself — the
        STATUS test_run_complete event stays honest."""
        with (
            patch("commits.get_uncommitted_files", return_value=["tests/test_x.py"]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="pytest",
                    stdout="===== 1 passed, 1 failed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        statuses = events_of_type(self._read_events(), EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1)
        metadata = statuses[0].get("metadata") or {}
        self.assertFalse(metadata.get("test_passed"))
        self.assertTrue(metadata.get("tdd_red"))

    def test_test_run_complete_carries_suite_size(self):
        """AC4: a 1-test scoped run is distinguishable from a full-suite run."""
        with (
            patch("commits.get_uncommitted_files", return_value=[]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="pytest",
                    stdout="===== 3 passed, 1 failed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        statuses = events_of_type(self._read_events(), EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1)
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("test_count"), 4)

    def test_green_phase_failure_after_test_only_commit_still_appends_concern(self):
        """Code-review #1: a test-only PRIOR COMMIT keeps
        _prior_commit_was_test_only True through the WHOLE green phase, so
        gating the concern on the commit leg would suppress a genuine
        green-phase failure and un-arm the stop gate. The concern gate must
        read the WORKING TREE — here impl code is in flight (buggy), so the
        failure is a real regression and MUST be flagged."""
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_COMMIT,
                    content="test: add failing spec for retry path",
                    files=["tests/test_x.py"],
                )
            ]
        )
        with (
            patch("commits.get_uncommitted_files", return_value=["src/app.py"]),
            patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="pytest",
                    stdout="===== 1 passed, 1 failed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        concerns = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(
            len(concerns),
            1,
            "a green-phase failure after a test-only commit is a real "
            "regression and must not be suppressed as a deliberate red",
        )
        self.assertEqual(concerns[0].get("severity"), "high")


class TestBashPostToolPushNoLongerNudges(_HookTestCase):
    """git push must NOT trigger the session-end checklist.

    The Stop hook (session_end_warning.py) owns the legitimate single-
    fire nudge at actual session end. Mid-session pushes were treating
    every git push as a session-end signal — false positive that fired
    multiple times per iteration. Dropped to fix concern 1d18655aa396.
    """

    def test_push_with_unresolved_concerns_does_not_warn(self):
        self._write_events(
            [make_event(EVENT_TYPE_CONCERN, content="Open issue", severity="medium")]
        )
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_push_does_not_nudge_summary(self):
        self._write_events([make_event(EVENT_TYPE_STATUS, content="All done")])
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
