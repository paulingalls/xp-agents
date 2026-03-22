#!/usr/bin/env python3
"""Tests for retrospective hook: retrospective analysis and nudge behavior.

Split from test_session.py.
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

        # Only 3 events — below threshold of 5
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

    def test_counts_events_after_last_retro(self):
        import retrospective

        # 10 events, retro at position 7, then 2 more — only 2 unanalyzed
        events = [make_event(content=f"event {i}") for i in range(7)]
        events.append(make_event("retrospective", content="retro done"))
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Only 2 events after retro — below threshold
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_retro_history_gathered(self):
        import retrospective

        # Write a previous retro file
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
        # Slimmed: content strings only, no event_refs/values
        self.assertEqual(data["previous_retros"][0]["keep"][0], "good TDD")

    def test_retro_history_limited_to_3(self):
        import retrospective

        # Write 5 retro files
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
        self.assertEqual(len(data["previous_retros"]), 2)

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
        self.assertIsNotNone(result)
        # Context should mention the event count
        self.assertIn("6", result)

    def test_event_type_counts(self):
        import retrospective

        events = [
            make_event("decision", content="decided X", topic="arch"),
            make_event("decision", content="decided Y", topic="api"),
            make_event("concern", content="issue A", severity="high"),
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

    def test_session_stats_key_exists(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("session_stats", data)

    def test_session_stats_status_count(self):
        import retrospective

        events = [
            make_event("status", content="Working", working_on=["a.py"]),
            make_event("status", content="Working2", working_on=["b.py"]),
            make_event("status", content="Working3", working_on=["c.py"]),
            make_event(content="filler 1"),
            make_event(content="filler 2"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["status_count"], 3)

    def test_session_stats_concerns(self):
        import retrospective

        c1 = make_event("concern", content="Issue A")
        c2 = make_event("concern", content="Issue B")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=["test.py"],
            metadata={"resolves": [c1["id"]]},
        )
        events = [c1, c2, resolver, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["concerns_raised"], 2)
        self.assertEqual(data["session_stats"]["concerns_resolved"], 1)

    def test_session_stats_questions(self):
        import retrospective

        q1 = make_event("question", content="Q1?", priority="\U0001f534")
        q2 = make_event("question", content="Q2?", priority="\U0001f7e1")
        a = make_event("answer", content="Yes", references=[q1["id"]])
        events = [q1, q2, a, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["questions_open"], 1)
        self.assertEqual(data["session_stats"]["questions_answered"], 1)

    def test_session_stats_decisions(self):
        import retrospective

        events = [
            make_event("decision", content="Use Postgres", topic="db"),
            make_event("decision", content="Use REST", topic="api"),
            make_event(content="f1"),
            make_event(content="f2"),
            make_event(content="f3"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["decisions_total"], 2)
        self.assertNotIn("decisions_draft", data["session_stats"])


# ===========================================================================
# M6.5: Retrospective nudge tests
# ===========================================================================


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
        self.assertIsNotNone(result)
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
