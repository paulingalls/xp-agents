#!/usr/bin/env python3
"""Tests for EVENT_TYPE_SESSION_SUMMARY schema registration (story-001).

Pins: constant + VALID_TYPES + CONTENT_BUDGETS (>=1500); validate_event
accept/reject behavior; E2E append.sh write.

The companion gate test_compact.py::TestEventTypeMatchCompleteness owns
membership-in-_VALIDATE_NO_TYPE_RULES enforcement for ALL event types —
do not duplicate that check here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _append_impl
import event_schema
from conftest import _TempRepoTestCase, make_event
from event_helpers import events_of_type


class TestSessionSummarySchema(unittest.TestCase):
    """Unit tests for the schema registration of session_summary."""

    def _event(self, **overrides) -> dict:
        return make_event(event_schema.EVENT_TYPE_SESSION_SUMMARY, **overrides)

    def test_constant_value(self):
        self.assertEqual(event_schema.EVENT_TYPE_SESSION_SUMMARY, "session_summary")

    def test_in_valid_types(self):
        self.assertIn(event_schema.EVENT_TYPE_SESSION_SUMMARY, event_schema.VALID_TYPES)

    def test_budget_at_least_1500(self):
        # AC1 pins the spec floor (>=1500), not the chosen 2000 — so future
        # tuning within spec doesn't churn this test.
        budget = event_schema.get_required_budget(
            event_schema.EVENT_TYPE_SESSION_SUMMARY
        )
        self.assertGreaterEqual(budget, 1500)

    def test_validate_accepts_well_formed(self):
        self.assertEqual(_append_impl.validate_event(self._event()), [])

    def test_validate_rejects_oversize_content(self):
        budget = event_schema.get_required_budget(
            event_schema.EVENT_TYPE_SESSION_SUMMARY
        )
        oversize = self._event(content="x" * (budget + 1))
        errors = _append_impl.validate_event(oversize)
        self.assertTrue(
            any("session_summary budget" in e for e in errors),
            f"expected budget error, got {errors!r}",
        )

    def test_validate_requires_universal_fields(self):
        for missing in ("id", "ts", "agent_id", "content"):
            event = self._event()
            del event[missing]
            errors = _append_impl.validate_event(event)
            self.assertTrue(
                any(f"Missing required field: {missing}" in e for e in errors),
                f"missing {missing!r}: expected required-field error, got {errors!r}",
            )


class TestSessionSummaryAppend(_TempRepoTestCase):
    """E2E: append.sh writes a session_summary event end-to-end."""

    def setUp(self):
        self._clear_events()

    def test_append_sh_writes_session_summary(self):
        r = self._run_append(
            "--type",
            "session_summary",
            "--agent",
            "test",
            "--content",
            "yesterday we shipped sprint-069 and started on /xp-end-session",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        summaries = events_of_type(
            self._read_events(), event_schema.EVENT_TYPE_SESSION_SUMMARY
        )
        self.assertEqual(len(summaries), 1)


if __name__ == "__main__":
    unittest.main()
