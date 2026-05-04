#!/usr/bin/env python3
"""Tests for retrospective decision wiring and try resolution.

Split from test_retrospective.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_STATUS,
)


class TestDecisionTopicsWiring(_HookTestCase):
    """evaluate_flags receives decision topics extracted from events."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_decision_topics_suppress_flags(self):
        import retrospective

        decision = make_event(
            EVENT_TYPE_DECISION,
            content="Adopted retro Try: kickoff exemption",
            topic="retro-try-kickoff-exemption",
        )
        code_event = make_event(
            EVENT_TYPE_STATUS, content="wrote code", working_on=["foo.py"]
        )
        filler = [make_event(content=f"f{i}") for i in range(80)]
        commit = make_event(EVENT_TYPE_COMMIT, content="git commit")
        events = [decision, code_event, *filler, commit]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        flag_metrics = [f["metric"] for f in data["digest"]["flags"]]
        self.assertNotIn("max_events_to_commit", flag_metrics)

    def test_no_decision_topics_flags_fire(self):
        import retrospective

        code_event = make_event(
            EVENT_TYPE_STATUS, content="wrote code", working_on=["foo.py"]
        )
        filler = [make_event(content=f"f{i}") for i in range(80)]
        commit = make_event(EVENT_TYPE_COMMIT, content="git commit")
        events = [code_event, *filler, commit]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        flag_metrics = [f["metric"] for f in data["digest"]["flags"]]
        self.assertIn("max_events_to_commit", flag_metrics)


class TestDroppedTryResolution(_HookTestCase):
    """Dropped Try items should be detected across session boundaries."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_dropped_try_detected_across_session_boundary(self):
        import retrospective

        old_concern_id = "aabb11223344"
        old_concern = make_event(
            EVENT_TYPE_CONCERN,
            id=old_concern_id,
            content="Test coverage gap",
            severity="medium",
        )
        retro_event = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Session retro: 3 keeps, 2 fixes, 1 try",
            keep=[{"content": "Good work", "event_refs": []}],
            fix=[],
            **{
                "try": [
                    {
                        "content": "Fix coverage",
                        "event_refs": [old_concern_id],
                    }
                ]
            },
        )
        retro_json = {
            "timestamp": "2026-04-19T00:00:00+00:00",
            "keep": [{"content": "Good work", "event_refs": []}],
            "fix": [],
            "try": [
                {
                    "content": "Fix coverage",
                    "event_refs": [old_concern_id],
                }
            ],
        }
        retro_file = self.smm_dir / "retrospectives" / "2026-04-19T00-00-00.json"
        retro_file.write_text(json.dumps(retro_json))

        drop_event = make_event(
            EVENT_TYPE_STATUS,
            content="Fix coverage",
            working_on=[],
            metadata={
                "resolves": [old_concern_id],
                "disposition": "dropped",
            },
        )
        new_events = [make_event(content=f"work {i}") for i in range(5)]

        self._write_events([old_concern, retro_event, drop_event, *new_events])
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        prev = data.get("previous_retros", [])
        self.assertTrue(len(prev) > 0)
        self.assertEqual(len(prev[0].get("try", [])), 0)
        self.assertEqual(len(prev[0].get("try_status", [])), 0)


if __name__ == "__main__":
    unittest.main()
