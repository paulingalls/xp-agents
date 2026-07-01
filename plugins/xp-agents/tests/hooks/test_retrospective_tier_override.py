#!/usr/bin/env python3
"""Tests for the tier_override recommendation-acceptance signal in retro input.

Story-005 (sprint-110 M3): retrospective.py samples status events with
metadata.action="tier_override" (the tier-picker hand-off audit trail) and
surfaces an override-count signal in the digest for the analyst's
heuristic-accuracy analysis.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS


def _override(story_id: str, picked: str, recommended: str) -> dict:
    """A tier_override audit event matching the 003->005 wire contract."""
    return make_event(
        EVENT_TYPE_STATUS,
        content=f"tier-override {story_id}: {picked} over rec {recommended}",
        working_on=[],
        metadata={
            "action": "tier_override",
            "story_id": story_id,
            "picked": picked,
            "recommended": recommended,
        },
    )


class TestTierOverrideSignal(_HookTestCase):
    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_and_load(self) -> dict:
        import retrospective

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_signal_present_with_overrides(self):
        # AC1: tier_override events -> signal present with override details.
        events = [
            _override("story-001", "haiku", "opus"),
            _override("story-002", "sonnet", "opus"),
            make_event(content="f1"),
            make_event(content="f2"),
            make_event(content="f3"),
        ]
        self._write_events(events)
        signal = self._run_and_load()["digest"]["tier_override_signal"]
        self.assertEqual(signal["override_count"], 2)
        self.assertEqual(
            signal["overrides"][0],
            {"story_id": "story-001", "picked": "haiku", "recommended": "opus"},
        )

    def test_signal_zero_when_no_overrides(self):
        # AC2: no tier_override events -> signal present, count 0, no error.
        events = [make_event(content=f"f{i}") for i in range(5)]
        self._write_events(events)
        signal = self._run_and_load()["digest"]["tier_override_signal"]
        self.assertEqual(signal["override_count"], 0)
        self.assertEqual(signal["overrides"], [])

    def test_override_count_e2e_and_excludes_non_status(self):
        # AC3 (e2e): two overrides reported; a non-status event carrying the
        # same action is NOT counted (pins the type=status half of the contract).
        events = [
            _override("story-003", "haiku", "opus"),
            _override("story-004", "haiku", "sonnet"),
            make_event(
                EVENT_TYPE_DECISION,
                content="decision text mentioning the tier_override action",
                metadata={
                    "action": "tier_override",
                    "story_id": "story-x",
                    "picked": "opus",
                    "recommended": "haiku",
                },
            ),
            make_event(content="f1"),
            make_event(content="f2"),
        ]
        self._write_events(events)
        signal = self._run_and_load()["digest"]["tier_override_signal"]
        self.assertEqual(signal["override_count"], 2)


if __name__ == "__main__":
    unittest.main()
