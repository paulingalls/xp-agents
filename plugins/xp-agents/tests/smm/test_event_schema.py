#!/usr/bin/env python3
"""Tests for event_schema STATUS_ACTION_* constants."""

import re
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import event_schema


class TestStatusActionConstants(unittest.TestCase):
    """Each constant exists with the expected value and the set is unique."""

    M1_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_SIMPLIFY_COMPLETE": "simplify_complete",
        "STATUS_ACTION_QR_COMPLETE": "qr_complete",
        "STATUS_ACTION_SECURITY_COMPLETE": "security_complete",
        "STATUS_ACTION_SECURITY_TRIAGE_STARTED": "security_triage_started",
        "STATUS_ACTION_SECURITY_TRIAGE_COMPLETE": "security_triage_complete",
        "STATUS_ACTION_PLAN_REVIEWED": "plan_reviewed",
        "STATUS_ACTION_HOUSEKEEPING_COMPLETE": "housekeeping_complete",
    }

    M2_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_FILE_WRITE": "file_write",
        "STATUS_ACTION_TEST_RUN_COMPLETE": "test_run_complete",
        "STATUS_ACTION_LINT_RESOLVED": "lint_resolved",
        "STATUS_ACTION_BASH_FAILED": "bash_failed",
        "STATUS_ACTION_COMMIT_SUCCESS": "commit_success",
    }

    M3_EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_SUBAGENT_COMPLETE": "subagent_complete",
        "STATUS_ACTION_PLAN_COMPLETED": "plan_completed",
        "STATUS_ACTION_PLAN_AWAITING_REVIEW": "plan_awaiting_review",
        "STATUS_ACTION_PLAN_EXITED": "plan_exited",
    }

    EXPECTED: ClassVar[dict[str, str]] = {**M1_EXPECTED, **M2_EXPECTED, **M3_EXPECTED}

    def test_each_constant_exists_with_expected_value(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(constant=name):
                self.assertTrue(
                    hasattr(event_schema, name),
                    f"event_schema missing constant {name}",
                )
                self.assertEqual(getattr(event_schema, name), expected)

    def test_action_vocabularies_distinct_from_legacy_status_actions(self):
        """M1/M2/M3 vocabularies must not collide with legacy status actions."""
        new_values = {getattr(event_schema, n) for n in self.EXPECTED}
        self.assertNotIn(event_schema.STATUS_ACTION_ITERATION_COMPLETE, new_values)
        self.assertNotIn(event_schema.STATUS_ACTION_SPRINT_RETRO_DONE, new_values)

    def test_m2_set_disjoint_from_m1_review_cycle(self):
        """M2 vocabulary must not collide with the M1 review-cycle vocabulary."""
        m1_values = frozenset(self.M1_EXPECTED.values())
        m2_values = frozenset(self.M2_EXPECTED.values())
        self.assertTrue(
            m1_values.isdisjoint(m2_values),
            f"M1 and M2 action vocabularies overlap: {m1_values & m2_values}",
        )

    def test_m3_set_disjoint_from_m1_m2(self):
        """M3 vocabulary must not collide with M1 or M2 vocabularies."""
        prior_values = frozenset(self.M1_EXPECTED.values()) | frozenset(
            self.M2_EXPECTED.values()
        )
        m3_values = frozenset(self.M3_EXPECTED.values())
        self.assertTrue(
            prior_values.isdisjoint(m3_values),
            f"M3 overlaps with prior vocabularies: {prior_values & m3_values}",
        )

    # Expected producer hook for each M2/M3 constant. The doc blocks in
    # event_schema.py must annotate every constant with its specific hook
    # filename on the same comment line — not just mention all hooks in a
    # shared block (which would let the test pass on mis-attribution).
    EXPECTED_PRODUCER: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_FILE_WRITE": "post_tool_use.py",
        "STATUS_ACTION_TEST_RUN_COMPLETE": "bash_post_tool.py",
        "STATUS_ACTION_LINT_RESOLVED": "lint_resolution.py",
        "STATUS_ACTION_BASH_FAILED": "bash_failure.py",
        "STATUS_ACTION_COMMIT_SUCCESS": "bash_post_tool.py",
        "STATUS_ACTION_SUBAGENT_COMPLETE": "subagent_stop.py",
        "STATUS_ACTION_PLAN_COMPLETED": "subagent_stop.py",
        "STATUS_ACTION_PLAN_AWAITING_REVIEW": "subagent_stop.py",
        "STATUS_ACTION_PLAN_EXITED": "post_tool_exit_plan.py",
    }

    def test_doc_block_names_emitting_hook(self):
        """The producer map names each constant on the same line as its hook."""
        source = event_schema.__file__
        assert source is not None, "event_schema module has no __file__"
        text = Path(source).read_text(encoding="utf-8")
        for name, expected_hook in self.EXPECTED_PRODUCER.items():
            with self.subTest(constant=name):
                # Match a comment line that names the constant and its hook
                # together — this is the producer map's load-bearing claim.
                pattern = re.compile(
                    rf"^\s*#.*\b{name}\b.*\b{re.escape(expected_hook)}\b",
                    re.MULTILINE,
                )
                self.assertRegex(
                    text,
                    pattern,
                    f"producer map must annotate {name} with {expected_hook} "
                    f"on a single comment line",
                )


if __name__ == "__main__":
    unittest.main()
