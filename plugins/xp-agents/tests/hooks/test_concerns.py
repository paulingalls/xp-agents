#!/usr/bin/env python3
"""Tests for scripts/concerns.py — focused on age-based filtering."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_SESSION_END, EVENT_TYPE_STATUS


class TestFilterBySessionAge(_HookTestCase):
    """concerns.filter_by_session_age(events, min_session_ends) returns open
    concerns that have survived `min_session_ends` or more session_end
    markers since they were raised. Resolved concerns are excluded."""

    def test_no_concerns_returns_empty(self):
        import concerns

        events = [
            make_event(EVENT_TYPE_SESSION_END, content="end"),
            make_event(EVENT_TYPE_SESSION_END, content="end"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])

    def test_concern_with_four_session_ends_is_stale(self):
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern")
        events = [
            c,
            make_event(EVENT_TYPE_SESSION_END, content="s1"),
            make_event(EVENT_TYPE_SESSION_END, content="s2"),
            make_event(EVENT_TYPE_SESSION_END, content="s3"),
            make_event(EVENT_TYPE_SESSION_END, content="s4"),
        ]
        stale = concerns.filter_by_session_age(events, 4)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["id"], c["id"])

    def test_fresh_concern_under_threshold_not_stale(self):
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Fresh concern")
        events = [
            c,
            make_event(EVENT_TYPE_SESSION_END, content="s1"),
            make_event(EVENT_TYPE_SESSION_END, content="s2"),
            make_event(EVENT_TYPE_SESSION_END, content="s3"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])

    def test_resolved_concern_excluded_even_if_old(self):
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Resolved long ago")
        r = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [c["id"]]},
        )
        events = [
            c,
            r,
            make_event(EVENT_TYPE_SESSION_END, content="s1"),
            make_event(EVENT_TYPE_SESSION_END, content="s2"),
            make_event(EVENT_TYPE_SESSION_END, content="s3"),
            make_event(EVENT_TYPE_SESSION_END, content="s4"),
            make_event(EVENT_TYPE_SESSION_END, content="s5"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])

    def test_concern_after_last_session_end_not_stale(self):
        """A concern raised after the most recent SESSION_END has 0 session
        markers since its appearance — never stale."""
        import concerns

        events = [
            make_event(EVENT_TYPE_SESSION_END, content="s1"),
            make_event(EVENT_TYPE_SESSION_END, content="s2"),
            make_event(EVENT_TYPE_SESSION_END, content="s3"),
            make_event(EVENT_TYPE_SESSION_END, content="s4"),
            make_event(EVENT_TYPE_CONCERN, content="Brand new"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])


if __name__ == "__main__":
    unittest.main()
