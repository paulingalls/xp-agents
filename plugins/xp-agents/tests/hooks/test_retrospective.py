#!/usr/bin/env python3
"""Tests for retrospective hook: core run() behavior, nudge, and decision wiring.

Split from test_session.py. Sprint, signals, and digest tests are in
test_retrospective_sprint.py, test_retrospective_signals.py, and
test_retrospective_digest.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_SPRINT,
)

# ===========================================================================
# retrospective.py tests
# ===========================================================================


class TestRetrospective(_HookTestCase):
    def setUp(self):
        super().setUp()
        # Create retrospectives/ directory
        self.retro_dir = self.smm_dir / "retrospectives"
        self.retro_dir.mkdir()

    def test_xp_agent_skips(self):
        import retrospective

        result = retrospective.run(
            {"session_id": "test", "source": "startup", "agent_type": "xp-retro"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_compact_source_skips(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(10)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_insufficient_events_no_file(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_sufficient_events_writes_file(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

    def test_retro_input_json_structure(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("unanalyzed_count", data)
        self.assertNotIn("events_since_last_retro", data)  # slimmed at write time
        self.assertIn("previous_retros", data)
        self.assertIn("event_type_counts", data)
        self.assertIn("digest", data)
        self.assertEqual(data["unanalyzed_count"], 6)

    def test_retro_input_includes_flags(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("flags", data["digest"])
        self.assertIsInstance(data["digest"]["flags"], list)

    def _has_high_zero_decision_flag(self) -> bool:
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        return any(
            f.get("metric") == "high_zero_decision_rate"
            for f in data["digest"]["flags"]
        )

    def test_high_zero_decision_rate_fires_when_majority_explicit_zero(self):
        """Wires retrospective.py:139 to pass events= so the
        high_zero_decision_rate signal fires in production. Per
        decision 3aebbd3df455, SessionStart retro passes the full
        events list (multi-sprint cumulative view).
        """
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        events.extend(
            make_event(
                EVENT_TYPE_DECISION,
                topic=f"zero-{i}",
                content=f"explicit zero {i}",
                metadata={"action": "explicit_zero"},
            )
            for i in range(4)
        )
        events.append(
            make_event(
                EVENT_TYPE_DECISION,
                topic="real-decision",
                content="a real decision",
            )
        )
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue(self._has_high_zero_decision_flag())

    def test_high_zero_decision_rate_silent_when_below_threshold(self):
        """Regression guard: flag must NOT fire when explicit_zero
        rate is below the 50% threshold.
        """
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        events.append(
            make_event(
                EVENT_TYPE_DECISION,
                topic="zero",
                content="explicit zero",
                metadata={"action": "explicit_zero"},
            )
        )
        events.extend(
            make_event(
                EVENT_TYPE_DECISION,
                topic=f"real-{i}",
                content=f"real decision {i}",
            )
            for i in range(3)
        )
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(self._has_high_zero_decision_flag())

    def test_counts_events_after_last_retro(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(7)]
        events.append(make_event(EVENT_TYPE_RETROSPECTIVE, content="retro done"))
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_find_unanalyzed_start_ignores_sprint_retro(self):
        """M1b: sprint retro events do not advance the session retro watermark."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        sprint_retro = make_event(EVENT_TYPE_RETROSPECTIVE, content="sprint retro")
        sprint_retro["metadata"] = {"action": "sprint_retro_done"}
        events.append(sprint_retro)
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        self.assertEqual(start, 0)

    def test_find_unanalyzed_start_stops_at_session_retro(self):
        """M1b: session retro events still advance the watermark as before."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        session_retro = make_event(EVENT_TYPE_RETROSPECTIVE, content="session retro")
        session_retro["metadata"] = {"action": "session_retro_done"}
        events.append(session_retro)
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        self.assertEqual(start, 4)

    def test_find_unanalyzed_start_legacy_retro_without_action(self):
        """M1b: legacy retrospective events with no metadata.action must still
        act as watermarks."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        events.append(make_event(EVENT_TYPE_RETROSPECTIVE, content="legacy retro"))
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        self.assertEqual(start, 4)

    def _sprint_md(self, sprint_id: str = "sprint-042") -> None:
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "foo", "done")],
                sprint_id=sprint_id,
                started="2026-04-08",
            )
        )

    def test_sprint_end_writes_retro_input_with_sizing(self):
        """M3: dangling sprint_end triggers session retro with sizing_analysis."""
        import retrospective

        self._sprint_md()
        events = [make_event(content=f"event {i}") for i in range(8)]
        events.append(
            make_event(
                EVENT_TYPE_SPRINT,
                content="Sprint ended",
                metadata={"sprint_id": "sprint-042", "action": "end"},
            )
        )
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        self.assertFalse((self.smm_dir / ".sprint-retro-input.json").exists())
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("sizing_analysis", data)

    def test_sprint_end_below_threshold_still_fires(self):
        """M3: sprint end bypasses RETRO_THRESHOLD."""
        import retrospective

        self._sprint_md()
        events = [
            make_event(
                EVENT_TYPE_SPRINT,
                content="Sprint started",
                metadata={"sprint_id": "sprint-042", "action": "start"},
            ),
            make_event(
                EVENT_TYPE_SPRINT,
                content="Sprint ended",
                metadata={"sprint_id": "sprint-042", "action": "end"},
            ),
        ]
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

    def test_session_retro_removes_stale_sprint_retro_input(self):
        """M4b: exclusive-file invariant."""
        import retrospective

        (self.smm_dir / ".sprint-retro-input.json").write_text('{"stale": true}')
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        self.assertFalse((self.smm_dir / ".sprint-retro-input.json").exists())

    def test_sprint_retro_fallback_to_session_when_sprint_missing(self):
        """M3: if sprint.json is missing, sizing_analysis is absent but
        session retro still runs normally."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(5)]
        events.append(
            make_event(
                EVENT_TYPE_SPRINT,
                content="Sprint ended",
                metadata={"sprint_id": "sprint-042", "action": "end"},
            )
        )
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        self.assertFalse((self.smm_dir / ".sprint-retro-input.json").exists())

    def test_find_unanalyzed_start_sprint_retro_after_session_retro(self):
        """M1b: scanner walks backwards past a sprint retro and still finds
        the session retro watermark correctly."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        session_retro = make_event(EVENT_TYPE_RETROSPECTIVE, content="session")
        session_retro["metadata"] = {"action": "session_retro_done"}
        events.append(session_retro)
        events.extend([make_event(content=f"mid {i}") for i in range(2)])
        sprint_retro = make_event(EVENT_TYPE_RETROSPECTIVE, content="sprint")
        sprint_retro["metadata"] = {"action": "sprint_retro_done"}
        events.append(sprint_retro)
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        start = retrospective._find_unanalyzed_start(events)
        self.assertEqual(start, 4)

    def test_retro_history_gathered(self):
        import retrospective

        retro_data = {"keep": [{"content": "good TDD"}], "fix": [], "try": []}
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["previous_retros"]), 1)
        self.assertEqual(data["previous_retros"][0]["keep"][0], "good TDD")

    def test_retro_history_limited_to_1(self):
        import retrospective

        for i in range(5):
            retro_data = {"keep": [{"content": f"retro {i}"}], "fix": [], "try": []}
            (self.retro_dir / f"2026-03-0{i + 1}T00-00-00.json").write_text(
                json.dumps(retro_data)
            )
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["previous_retros"]), 1)

    def test_retro_history_empty_dir(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["previous_retros"], [])

    def test_graceful_no_smm_dir(self):
        import retrospective

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_context_returned_when_needed(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertIn("6", result)

    def test_event_type_counts(self):
        import retrospective

        events = [
            make_event(EVENT_TYPE_DECISION, content="decided X", topic="arch"),
            make_event(EVENT_TYPE_DECISION, content="decided Y", topic="api"),
            make_event(EVENT_TYPE_CONCERN, content="issue A", severity="high"),
            make_event(content="input 1"),
            make_event(content="input 2"),
            make_event(content="input 3"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["event_type_counts"]["decision"], 2)
        self.assertEqual(data["event_type_counts"]["concern"], 1)
        self.assertEqual(data["event_type_counts"]["customer_input"], 3)


class TestRetrospectiveNudge(_HookTestCase):
    """M6.5: retrospective.py should nudge invoking xp-retrospective."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_retro_context_has_nudge(self):
        import retrospective

        events = [make_event(content=f"e{i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertIn("xp-kickoff", result)

    def test_retro_below_threshold_no_nudge(self):
        import retrospective

        self._write_events([make_event()])
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
