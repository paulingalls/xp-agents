#!/usr/bin/env python3
"""Tests for retrospective session stats computation.

Split from test_retrospective.py — session stats tests exercise
_compute_session_stats via the retrospective.run() entry point.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


class TestSessionStats(_HookTestCase):
    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

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

    def test_session_stats_iterations_completed(self):
        import retrospective

        events = [
            make_event("status", content="work", working_on=["a.py"]),
            make_event(
                "status",
                content="Iteration complete \u2014 accept verification done.",
                working_on=[],
                metadata={"action": "iteration_complete"},
            ),
            make_event("status", content="more work", working_on=["b.py"]),
            make_event(
                "status",
                content="Iteration complete \u2014 accept verification done.",
                working_on=[],
                metadata={"action": "iteration_complete"},
            ),
            make_event(content="filler"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["iterations_completed"], 2)

    def test_session_stats_zero_iterations(self):
        import retrospective

        events = [make_event(content=f"work {i}") for i in range(5)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["iterations_completed"], 0)

    def test_session_stats_solo_per_agent_matches_aggregate(self):
        """Solo session: per_agent dict has 1 key matching aggregate values."""
        import retrospective

        events = [
            make_event("status", content="Working", working_on=["a.py"]),
            make_event("concern", content="Issue A"),
            make_event("decision", content="Use X", topic="arch"),
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
        stats = data["session_stats"]
        self.assertIn("per_agent", stats)
        self.assertEqual(len(stats["per_agent"]), 1)
        self.assertIn("main", stats["per_agent"])
        agent_stats = stats["per_agent"]["main"]
        self.assertEqual(agent_stats["status_count"], stats["status_count"])
        self.assertEqual(agent_stats["concerns_raised"], stats["concerns_raised"])
        self.assertEqual(agent_stats["decisions_total"], stats["decisions_total"])

    def test_session_stats_parallel_per_agent_scoped(self):
        """Parallel-teammate session: per-agent stats scoped to each agent."""
        import retrospective

        events = [
            make_event(
                "status", content="Working", working_on=["a.py"], agent_id="teammate-1"
            ),
            make_event(
                "status", content="Working", working_on=["b.py"], agent_id="teammate-1"
            ),
            make_event(
                "status", content="Working", working_on=["c.py"], agent_id="teammate-2"
            ),
            make_event("concern", content="Issue A", agent_id="teammate-1"),
            make_event("concern", content="Issue B", agent_id="teammate-2"),
            make_event("concern", content="Issue C", agent_id="teammate-2"),
            make_event(
                "decision", content="Use X", topic="arch", agent_id="teammate-1"
            ),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        stats = data["session_stats"]
        self.assertIn("per_agent", stats)
        self.assertEqual(len(stats["per_agent"]), 2)
        t1 = stats["per_agent"]["teammate-1"]
        t2 = stats["per_agent"]["teammate-2"]
        self.assertEqual(t1["status_count"], 2)
        self.assertEqual(t1["concerns_raised"], 1)
        self.assertEqual(t1["decisions_total"], 1)
        self.assertEqual(t2["status_count"], 1)
        self.assertEqual(t2["concerns_raised"], 2)
        self.assertEqual(t2["decisions_total"], 0)


if __name__ == "__main__":
    unittest.main()
