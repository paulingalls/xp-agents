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

    EXPECTED: ClassVar[dict[str, str]] = {**M1_EXPECTED, **M2_EXPECTED}

    def test_each_constant_exists_with_expected_value(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(constant=name):
                self.assertTrue(
                    hasattr(event_schema, name),
                    f"event_schema missing constant {name}",
                )
                self.assertEqual(getattr(event_schema, name), expected)

    def test_constants_distinct_from_existing_iteration_complete(self):
        """New review-cycle constants must not collide with existing actions."""
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

    # Expected producer hook for each M2 constant. The doc block in
    # event_schema.py must annotate every constant with its specific hook
    # filename on the same comment line — not just mention all hooks in a
    # shared block (which would let the test pass on mis-attribution).
    EXPECTED_PRODUCER: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_FILE_WRITE": "post_tool_use.py",
        "STATUS_ACTION_TEST_RUN_COMPLETE": "bash_post_tool.py",
        "STATUS_ACTION_LINT_RESOLVED": "bash_post_tool.py",
        "STATUS_ACTION_BASH_FAILED": "bash_failure.py",
        "STATUS_ACTION_COMMIT_SUCCESS": "bash_post_tool.py",
    }

    def test_m2_doc_block_names_emitting_hook(self):
        """The producer map names each M2 constant on the same line as its hook."""
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
