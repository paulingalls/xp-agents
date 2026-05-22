#!/usr/bin/env python3
"""Tests for scripts/concerns.py — focused on age-based filtering."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)


class TestFilterBySessionAge(_HookTestCase):
    """concerns.filter_by_session_age(events, min_anchors) returns open
    concerns that have survived `min_anchors` or more session_started
    markers since they were raised. Resolved concerns are excluded."""

    def test_no_concerns_returns_empty(self):
        import concerns

        events = [
            make_event(EVENT_TYPE_SESSION_STARTED, content="start"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="start"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])

    def test_precomputed_anchor_positions_skips_internal_walk(self):
        """Concern 637b7fb61f30: caller (SessionStart's stale-concern sweep)
        already walks events to compute the session_started anchor positions
        for its own use; passing them back to filter_by_session_age avoids
        the redundant second pass. Behavior must be identical with or without
        the param."""
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern")
        events = [
            c,
            make_event(EVENT_TYPE_SESSION_STARTED, content="s1"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s2"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s3"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s4"),
        ]
        positions = [
            i
            for i, e in enumerate(events)
            if e.get("type") == EVENT_TYPE_SESSION_STARTED
        ]
        stale = concerns.filter_by_session_age(events, 4, anchor_positions=positions)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["id"], c["id"])

    def test_concern_with_four_anchors_is_stale(self):
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern")
        events = [
            c,
            make_event(EVENT_TYPE_SESSION_STARTED, content="s1"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s2"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s3"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s4"),
        ]
        stale = concerns.filter_by_session_age(events, 4)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["id"], c["id"])

    def test_fresh_concern_under_threshold_not_stale(self):
        import concerns

        c = make_event(EVENT_TYPE_CONCERN, content="Fresh concern")
        events = [
            c,
            make_event(EVENT_TYPE_SESSION_STARTED, content="s1"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s2"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s3"),
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
            make_event(EVENT_TYPE_SESSION_STARTED, content="s1"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s2"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s3"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s4"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s5"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])

    def test_concern_after_last_anchor_not_stale(self):
        """A concern raised after the most recent SESSION_STARTED has 0
        session markers since its appearance — never stale."""
        import concerns

        events = [
            make_event(EVENT_TYPE_SESSION_STARTED, content="s1"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s2"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s3"),
            make_event(EVENT_TYPE_SESSION_STARTED, content="s4"),
            make_event(EVENT_TYPE_CONCERN, content="Brand new"),
        ]
        self.assertEqual(concerns.filter_by_session_age(events, 4), [])


if __name__ == "__main__":
    unittest.main()
