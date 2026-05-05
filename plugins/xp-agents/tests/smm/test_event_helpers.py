#!/usr/bin/env python3
"""Tests for event_helpers.events_of_type."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT, EVENT_TYPE_STATUS


class TestEventsOfType(unittest.TestCase):
    def test_single_match_in_mixed_list(self):
        s = make_event(EVENT_TYPE_STATUS)
        c = make_event(EVENT_TYPE_CONCERN)
        d = make_event(EVENT_TYPE_DEBT)
        self.assertEqual(events_of_type([s, c, d], EVENT_TYPE_CONCERN), [c])

    def test_multiple_matches_preserve_order(self):
        a = make_event(EVENT_TYPE_STATUS)
        b = make_event(EVENT_TYPE_STATUS)
        c = make_event(EVENT_TYPE_CONCERN)
        d = make_event(EVENT_TYPE_STATUS)
        self.assertEqual(events_of_type([a, b, c, d], EVENT_TYPE_STATUS), [a, b, d])

    def test_no_matches_returns_empty(self):
        s = make_event(EVENT_TYPE_STATUS)
        self.assertEqual(events_of_type([s], EVENT_TYPE_CONCERN), [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(events_of_type([], EVENT_TYPE_STATUS), [])

    def test_event_without_type_key_excluded(self):
        # Bare dict — make_event always sets type, can't represent this case
        no_type = {"id": "no-type"}
        with_type = make_event(EVENT_TYPE_STATUS)
        self.assertEqual(
            events_of_type([no_type, with_type], EVENT_TYPE_STATUS), [with_type]
        )

    def test_generator_input_returns_list(self):
        s = make_event(EVENT_TYPE_STATUS)
        c = make_event(EVENT_TYPE_CONCERN)

        def gen():
            yield s
            yield c

        result = events_of_type(gen(), EVENT_TYPE_STATUS)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [s])


if __name__ == "__main__":
    unittest.main()
