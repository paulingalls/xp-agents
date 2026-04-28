#!/usr/bin/env python3
"""Tests for event_schema STATUS_ACTION_* constants.

Sprint-041 / story-001 — adds the review-cycle lifecycle action vocabulary.
"""

import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import event_schema


class TestStatusActionConstants(unittest.TestCase):
    """Each constant exists with the expected value and the set is unique."""

    EXPECTED: ClassVar[dict[str, str]] = {
        "STATUS_ACTION_SIMPLIFY_COMPLETE": "simplify_complete",
        "STATUS_ACTION_QR_COMPLETE": "qr_complete",
        "STATUS_ACTION_SECURITY_COMPLETE": "security_complete",
        "STATUS_ACTION_SECURITY_TRIAGE_STARTED": "security_triage_started",
        "STATUS_ACTION_SECURITY_TRIAGE_COMPLETE": "security_triage_complete",
        "STATUS_ACTION_PLAN_REVIEWED": "plan_reviewed",
        "STATUS_ACTION_HOUSEKEEPING_COMPLETE": "housekeeping_complete",
    }

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


if __name__ == "__main__":
    unittest.main()
