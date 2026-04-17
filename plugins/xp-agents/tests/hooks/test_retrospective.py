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

    def test_find_unanalyzed_start_ignores_sprint_retro(self):
        """M1b: sprint retro events do not advance the session retro watermark.

        Scenario: sprint retro ran at end of last session, now a new session
        starts. The session retro scanner should count events BEFORE the
        sprint retro, not stop at it.
        """
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        sprint_retro = make_event("retrospective", content="sprint retro")
        sprint_retro["metadata"] = {"action": "sprint_retro_done"}
        events.append(sprint_retro)
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        # Sprint retro is transparent — all 7 events are unanalyzed from the
        # session retro's perspective.
        self.assertEqual(start, 0)

    def test_find_unanalyzed_start_stops_at_session_retro(self):
        """M1b: session retro events still advance the watermark as before."""
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        session_retro = make_event("retrospective", content="session retro")
        session_retro["metadata"] = {"action": "session_retro_done"}
        events.append(session_retro)
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        # Stops just after the session retro at index 3.
        self.assertEqual(start, 4)

    def test_find_unanalyzed_start_legacy_retro_without_action(self):
        """M1b: legacy retrospective events with no metadata.action must still
        act as watermarks (backwards compat for pre-M1 event logs like the
        xp-agents-inline test project).
        """
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        # Legacy retro: no metadata at all
        events.append(make_event("retrospective", content="legacy retro"))
        events.extend([make_event(content=f"post {i}") for i in range(3)])
        start = retrospective._find_unanalyzed_start(events)
        self.assertEqual(start, 4)

    def _sprint_md(self, sprint_id: str = "sprint-042") -> None:
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "foo", "S", "done")],
                sprint_id=sprint_id,
                started="2026-04-08",
            )
        )

    def test_sprint_end_writes_retro_input_with_sizing(self):
        """M3: dangling sprint_end triggers session retro with sizing_analysis
        in .retro-input.json (replaces old separate sprint-retro path)."""
        import retrospective

        self._sprint_md()
        events = [make_event(content=f"event {i}") for i in range(8)]
        events.append(
            make_event(
                "sprint",
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
        """M3: sprint end bypasses RETRO_THRESHOLD — session retro fires
        with sizing_analysis even with fewer than 5 unanalyzed events."""
        import retrospective

        self._sprint_md()
        events = [
            make_event(
                "sprint",
                content="Sprint started",
                metadata={"sprint_id": "sprint-042", "action": "start"},
            ),
            make_event(
                "sprint",
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
        """M4b: exclusive-file invariant — session retro path unlinks
        .sprint-retro-input.json if present."""
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

        # No sprint.json — prep will return None.
        events = [make_event(content=f"event {i}") for i in range(5)]
        events.append(
            make_event(
                "sprint",
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
        the session retro watermark correctly.
        """
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(3)]
        session_retro = make_event("retrospective", content="session")
        session_retro["metadata"] = {"action": "session_retro_done"}
        events.append(session_retro)  # index 3
        events.extend([make_event(content=f"mid {i}") for i in range(2)])
        sprint_retro = make_event("retrospective", content="sprint")
        sprint_retro["metadata"] = {"action": "sprint_retro_done"}
        events.append(sprint_retro)  # index 6 — ignored
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        start = retrospective._find_unanalyzed_start(events)
        # Stops at session retro index 3, returns 4
        self.assertEqual(start, 4)

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

    def test_session_stats_iterations_completed(self):
        import retrospective

        events = [
            make_event("status", content="work", working_on=["a.py"]),
            make_event(
                "status",
                content="Iteration complete — accept verification done.",
                working_on=[],
                metadata={"action": "iteration_complete"},
            ),
            make_event("status", content="more work", working_on=["b.py"]),
            make_event(
                "status",
                content="Iteration complete — accept verification done.",
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


# ===========================================================================
# M3: Sprint sizing in session retro
# ===========================================================================


class TestSprintSizingInRetro(_HookTestCase):
    """M3: when a sprint ended, .retro-input.json includes sizing_analysis."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _setup_sprint_with_end(self, event_count: int = 8) -> list[dict]:
        """Write sprint.json and return events including sprint_end."""
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Add auth",
                        "M",
                        "done",
                        file_domain=["scripts/auth.py \u2014 add login"],
                    ),
                    _s(
                        "story-002",
                        "Add tests",
                        "S",
                        "done",
                        file_domain=["tests/test_auth.py \u2014 auth tests"],
                    ),
                ],
                sprint_id="sprint-042",
                started="2026-04-01",
                goal="Build auth",
            )
        )
        events = [make_event(content=f"event {i}") for i in range(event_count)]
        events.append(
            make_event(
                "commit",
                content="Committed: add login",
                files=["scripts/auth.py"],
                ts="2026-04-05T10:00:00+00:00",
                metadata={
                    "code_commit": True,
                    "commit_hash": "abc123",
                    "story_id": "story-001",
                },
            )
        )
        events.append(
            make_event(
                "sprint",
                content="Sprint ended",
                metadata={"sprint_id": "sprint-042", "action": "end"},
            )
        )
        return events

    def test_sprint_ended_retro_input_has_sizing_analysis(self):
        import retrospective

        events = self._setup_sprint_with_end()
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("sizing_analysis", data)
        sizing = data["sizing_analysis"]
        self.assertEqual(sizing["sprint_id"], "sprint-042")
        self.assertEqual(sizing["velocity"]["stories_delivered"], 2)
        self.assertIn("per_story", sizing)
        self.assertIn("per_size", sizing)

    def test_no_sprint_ended_no_sizing(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertNotIn("sizing_analysis", data)

    def test_sprint_ended_below_threshold_still_fires(self):
        """Sprint end should bypass the RETRO_THRESHOLD and produce
        .retro-input.json with sizing_analysis even with few events."""
        import retrospective

        events = self._setup_sprint_with_end(event_count=2)
        self._write_events(events)

        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("sizing_analysis", data)

    def test_sprint_ended_cleans_stale_sprint_retro_input(self):
        """Even with sprint end, old .sprint-retro-input.json is cleaned up."""
        import retrospective

        (self.smm_dir / ".sprint-retro-input.json").write_text('{"stale": true}')
        events = self._setup_sprint_with_end()
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".sprint-retro-input.json").exists())
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

    def test_sizing_analysis_attributes_commits_to_stories(self):
        import retrospective

        events = self._setup_sprint_with_end()
        self._write_events(events)

        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        sizing = data["sizing_analysis"]
        story_001 = next(s for s in sizing["per_story"] if s["id"] == "story-001")
        self.assertEqual(story_001["commits"], 1)
        self.assertEqual(story_001["in_domain_files"], 1)


# ===========================================================================
# M3: Sprint detection
# ===========================================================================


def _sprint_start(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} started",
        metadata={"sprint_id": sprint_id, "action": "start"},
    )


def _sprint_end(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} ended",
        metadata={"sprint_id": sprint_id, "action": "end"},
    )


def _sprint_retro_done(sprint_id: str) -> dict:
    return make_event(
        "status",
        content="Sprint retrospective complete.",
        metadata={"sprint_id": sprint_id, "action": "sprint_retro_done"},
    )


class TestNeedsSprintRetro(unittest.TestCase):
    """needs_sprint_retro(events) returns sprint_id or None."""

    def test_dangling_sprint_end_returns_sprint_id(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            make_event(content="work during sprint"),
            _sprint_end("s-001"),
            make_event(content="post-sprint activity"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-001")

    def test_sprint_end_with_matching_retro_done_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            make_event(content="post-retro activity"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_no_sprint_end_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            make_event(content="mid-sprint work"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_empty_events_returns_none(self):
        import retrospective

        self.assertIsNone(retrospective.needs_sprint_retro([]))

    def test_abandoned_sprint_returns_none(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_start("s-002"),
            make_event(content="new sprint work"),
        ]
        self.assertIsNone(retrospective.needs_sprint_retro(events))

    def test_stale_retro_done_different_sprint_id(self):
        import retrospective

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_start("s-002"),
            _sprint_end("s-002"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-002")

    def test_most_recent_sprint_end_checked(self):
        import retrospective

        events = [
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_end("s-002"),
            _sprint_retro_done("s-002"),
            _sprint_end("s-003"),
        ]
        self.assertEqual(retrospective.needs_sprint_retro(events), "s-003")


# ===========================================================================
# M6.5: Retrospective nudge tests
# ===========================================================================


class TestHonestySignals(unittest.TestCase):
    """Tests for _build_honesty_signals unique file counting."""

    def _make_write_status(self, path: str) -> dict:
        return make_event("status", content=f"Wrote to {path}", working_on=[path])

    def _make_test_status(self) -> dict:
        return make_event("status", content="Tests: 5 passed, 0 failed", working_on=[])

    def test_counts_unique_files_not_raw_writes(self):
        """4 writes to same file between tests should count as 1."""
        import honesty_signals

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_counts_different_files(self):
        """3 different files between tests should count as 3."""
        import honesty_signals

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/db.py"),
            self._make_write_status("src/api.py"),
            self._make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_resets_on_test_run(self):
        """Unique file set resets after each test run."""
        import honesty_signals

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/db.py"),
            self._make_test_status(),
            self._make_write_status("src/api.py"),
            self._make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_excludes_test_files(self):
        """Test file writes should not count."""
        import honesty_signals

        events = [
            self._make_write_status("tests/test_app.py"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_excludes_non_code_files(self):
        """Non-code files (md, json, etc) should not count."""
        import honesty_signals

        events = [
            self._make_write_status("README.md"),
            self._make_write_status("config.json"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)


class TestTriageCounting(unittest.TestCase):
    """Tests for commits_without_triage counting in _build_honesty_signals."""

    def test_commit_event_without_triage_counted(self):
        """Commit event without preceding triage is counted as untriaged."""
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 1)
        self.assertEqual(signals["total_commits"], 1)

    def test_commit_event_with_triage_not_counted(self):
        """Commit event preceded by triage is not counted as untriaged."""
        import honesty_signals

        events = [
            make_event(
                "status",
                content="Security triage started — reviewing staged changes",
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 0)

    def test_commit_event_with_security_review_not_counted(self):
        """Commit preceded by /security-review event is not counted as untriaged."""
        import honesty_signals

        events = [
            make_event(
                "status",
                content="Security review complete — full review performed",
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 0)

    def test_non_code_commit_event_not_counted(self):
        """Non-code commit (docs-only) without triage is NOT counted as untriaged."""
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Update docs",
                metadata={"code_commit": False},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 0)

    def test_legacy_status_commit_backward_compat(self):
        """Legacy status commit events still detected (backward compat)."""
        import honesty_signals

        events = [
            make_event("status", content="Committed: Old commit"),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 1)
        self.assertEqual(signals["total_commits"], 1)


class TestCodeCommitsAndPlanningEvents(unittest.TestCase):
    """Tests for code_commits and planning_events in honesty_signals."""

    def test_counts_code_commits(self):
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Fix bug",
                metadata={"code_commit": True, "commit_hash": "abc"},
            ),
            make_event(
                "commit",
                content="Update docs",
                metadata={"code_commit": False, "commit_hash": "def"},
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "ghi"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["code_commits"], 2)

    def test_counts_planning_events(self):
        import honesty_signals

        events = [
            make_event(
                "status",
                content="plan_awaiting_review: Plan completed",
            ),
            make_event("status", content="Working on tests"),
            make_event(
                "status",
                content="plan_awaiting_review: Plan completed",
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 2)

    def test_no_planning_events(self):
        import honesty_signals

        events = [make_event("status", content="Working on tests")]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 0)


class TestCommitAsSignalEvent(_HookTestCase):
    """Commit events should appear in the retro digest as signal events."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_commit_in_signal_events(self):
        """Commit events flow through as signal events in the digest."""
        import retrospective

        commit = make_event(
            "commit",
            content="Fix auth bug\n\nDetailed explanation of the fix.",
            metadata={"commit_hash": "abc123", "code_commit": True},
            files=["src/auth.py"],
        )
        self._write_events([make_event()] * 5 + [commit])
        context = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(context)
        data = json.loads((self.smm_dir / ".retro-input.json").read_text())
        signal_types = [e["type"] for e in data["digest"]["signal_events"]]
        self.assertIn("commit", signal_types)


class TestRetrospectiveResolvedConcerns(_HookTestCase):
    """Resolved concerns should be rolled up to counts, not included in full."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_resolved_concerns_excluded_from_signal_events(self):
        import retrospective

        c1 = make_event("concern", content="Lint error in foo.py: F401")
        c2 = make_event("concern", content="Unresolved real concern")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=["foo.py"],
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
        signal_ids = {e["id"] for e in data["digest"]["signal_events"]}
        # Resolved concern excluded
        self.assertNotIn(c1["id"], signal_ids)
        # Unresolved concern included
        self.assertIn(c2["id"], signal_ids)

    def test_resolved_concerns_counted_in_digest(self):
        import retrospective

        c1 = make_event("concern", content="Lint error")
        c2 = make_event("concern", content="Test failure")
        resolver = make_event(
            "status",
            content="Fixed both",
            working_on=[],
            metadata={"resolves": [c1["id"], c2["id"]]},
        )
        events = [c1, c2, resolver, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["digest"]["resolved_concern_count"], 2)

    def test_resolved_concerns_excluded_from_concern_groups(self):
        import retrospective

        c1 = make_event("concern", content="Lint error in foo.py")
        c2 = make_event("concern", content="Lint error in bar.py")
        c3 = make_event("concern", content="Real design concern")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [c1["id"], c2["id"]]},
        )
        events = [
            c1,
            c2,
            c3,
            resolver,
            make_event(content="f1"),
            make_event(content="f2"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        group_keys = [g["key"] for g in data["digest"]["concern_groups"]]
        self.assertIn("Real design concern", group_keys)
        # Resolved lint concerns should not appear in groups
        self.assertNotIn("Lint error in foo.py", group_keys)


class TestRetrospectiveDigestResolutions(_HookTestCase):
    """digest.resolutions exposes all 6 resolution types to the retro analyst."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_and_load(self, events):
        import retrospective

        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_digest_includes_debt_resolutions(self):
        debt = make_event("debt", content="Fix the thing later")
        resolver = make_event(
            "status",
            content="Debt closed: fixed it",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        self.assertIn(debt["id"], resolutions)
        entry = resolutions[debt["id"]]
        self.assertEqual(entry["type"], "debt")
        self.assertEqual(entry["resolver_id"], resolver["id"])
        self.assertIn("Debt closed", entry["resolver_content"])

    def test_digest_includes_question_answers(self):
        q = make_event("question", content="What do?")
        resolver = make_event(
            "status",
            content="Answered via resolve",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        data = self._run_and_load(
            [q, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        self.assertIn(q["id"], data["digest"]["resolutions"])
        self.assertEqual(data["digest"]["resolutions"][q["id"]]["type"], "question")

    def test_digest_includes_all_resolution_types(self):
        goal = make_event("goal", content="Ship feature X")
        assumption = make_event("assumption", content="Assuming X works like Y")
        concern = make_event("concern", content="A worry")
        decision = make_event("decision", content="Use X", topic="x-topic")
        resolver = make_event(
            "status",
            content="Everything resolved",
            working_on=[],
            metadata={
                "resolves": [
                    goal["id"],
                    assumption["id"],
                    concern["id"],
                    decision["id"],
                ]
            },
        )
        data = self._run_and_load(
            [goal, assumption, concern, decision, resolver]
            + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        self.assertEqual(resolutions[goal["id"]]["type"], "goal")
        self.assertEqual(resolutions[assumption["id"]]["type"], "assumption")
        self.assertEqual(resolutions[concern["id"]]["type"], "concern")
        self.assertEqual(resolutions[decision["id"]]["type"], "decision")

    def test_resolutions_resolver_content_truncated_to_200(self):
        debt = make_event("debt", content="Thing")
        long_content = "x" * 500
        resolver = make_event(
            "status",
            content=long_content,
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        self.assertEqual(
            len(data["digest"]["resolutions"][debt["id"]]["resolver_content"]),
            200,
        )

    def test_resolutions_use_short_ids(self):
        debt = make_event("debt", content="Thing")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        data = self._run_and_load(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        for key in data["digest"]["resolutions"]:
            self.assertEqual(len(key), 12, f"key {key!r} is not 12 chars")

    def test_resolutions_single_bucket_invariant(self):
        debt = make_event("debt", content="Thing 1")
        goal = make_event("goal", content="Thing 2")
        resolver = make_event(
            "status",
            content="Both fixed",
            working_on=[],
            metadata={"resolves": [debt["id"], goal["id"]]},
        )
        data = self._run_and_load(
            [debt, goal, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        resolutions = data["digest"]["resolutions"]
        # Each target ID lands in exactly one bucket — no duplication across types.
        self.assertEqual(len(resolutions), 2)
        self.assertEqual(resolutions[debt["id"]]["type"], "debt")
        self.assertEqual(resolutions[goal["id"]]["type"], "goal")


class TestGatherRetroHistoryTryShape(_HookTestCase):
    """try items in previous_retros preserve {content, event_refs} shape."""

    def setUp(self):
        super().setUp()
        self.retro_dir = self.smm_dir / "retrospectives"
        self.retro_dir.mkdir()

    def test_gather_retro_history_preserves_try_event_refs(self):
        import retro_history

        retro_data = {
            "keep": [{"content": "TDD held", "event_refs": ["aaa11111"]}],
            "fix": [{"content": "no status events"}],
            "try": [
                {
                    "content": "close debt 9cdd4617",
                    "event_refs": ["9cdd4617-aaaa-bbbb-cccc-dddddddddddd"],
                }
            ],
        }
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result), 1)
        # keep and fix stay content-only
        self.assertEqual(result[0]["keep"], ["TDD held"])
        self.assertEqual(result[0]["fix"], ["no status events"])
        # try becomes list of {content, event_refs}
        self.assertEqual(len(result[0]["try"]), 1)
        self.assertEqual(result[0]["try"][0]["content"], "close debt 9cdd4617")
        self.assertEqual(
            result[0]["try"][0]["event_refs"],
            ["9cdd4617-aaaa-bbbb-cccc-dddddddddddd"],
        )

    def test_gather_retro_history_handles_legacy_string_try(self):
        import retro_history

        # Old shape: try is a list of strings (pre-Commit-2 format).
        retro_data = {
            "keep": [{"content": "good session"}],
            "fix": [],
            "try": ["be more careful"],
        }
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result[0]["try"]), 1)
        self.assertEqual(result[0]["try"][0]["content"], "be more careful")
        self.assertEqual(result[0]["try"][0]["event_refs"], [])


class TestAnnotateTryStatus(_HookTestCase):
    """_annotate_try_status flags Try items whose IDs were resolved this session."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_and_load_with_retro(self, retro_data, events):
        import retrospective

        (self.smm_dir / "retrospectives" / "2026-03-10T00-00-00.json").write_text(
            json.dumps(retro_data)
        )
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def test_annotate_try_with_resolved_debt_id_in_content(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"close debt {debt['id']} in first commit"}],
        }
        data = self._run_and_load_with_retro(
            retro_data,
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)],
        )
        try_status = data["previous_retros"][0]["try_status"]
        self.assertEqual(len(try_status), 1)
        self.assertTrue(try_status[0]["resolved_this_session"])
        self.assertEqual(try_status[0]["resolver_id"], resolver["id"])

    def test_annotate_try_with_event_refs_only(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [
                {
                    "content": "be more careful",  # no hex tokens in content
                    "event_refs": [debt["id"]],
                }
            ],
        }
        data = self._run_and_load_with_retro(
            retro_data,
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)],
        )
        self.assertTrue(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_try_with_unresolved_id_not_flagged(self):
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": "close debt deadbeef12"}],  # ID not in session
        }
        data = self._run_and_load_with_retro(
            retro_data, [make_event(content=f"e{i}") for i in range(6)]
        )
        self.assertFalse(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_try_with_no_hex_tokens(self):
        retro_data = {
            "keep": [],
            "fix": [],
            "try": [{"content": "be more careful next session"}],
        }
        data = self._run_and_load_with_retro(
            retro_data, [make_event(content=f"e{i}") for i in range(6)]
        )
        self.assertFalse(
            data["previous_retros"][0]["try_status"][0]["resolved_this_session"]
        )

    def test_annotate_only_most_recent_retro(self):
        debt = make_event("debt", content="Fix later")
        resolver = make_event(
            "status",
            content="Debt closed",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        short = debt["id"]
        # Two previous retros — only the most recent gets try_status
        old_retro = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"old mention {short}"}],
        }
        new_retro = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"new mention {short}"}],
        }
        (self.smm_dir / "retrospectives" / "2026-03-09T00-00-00.json").write_text(
            json.dumps(old_retro)
        )
        (self.smm_dir / "retrospectives" / "2026-03-10T00-00-00.json").write_text(
            json.dumps(new_retro)
        )
        import retrospective

        self._write_events(
            [debt, resolver] + [make_event(content=f"e{i}") for i in range(4)]
        )
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        # Most recent retro (index 0) has try_status
        self.assertIn("try_status", data["previous_retros"][0])
        # Older retros do not
        self.assertNotIn("try_status", data["previous_retros"][1])

    def test_annotate_empty_previous_retros(self):
        data = self._run_and_load_with_retro(
            {"keep": [], "fix": [], "try": []},
            [make_event(content=f"e{i}") for i in range(6)],
        )
        # Empty try → empty try_status
        self.assertEqual(data["previous_retros"][0]["try_status"], [])

    def test_annotate_no_previous_retros(self):
        import retrospective

        # No retros directory content
        self._write_events([make_event(content=f"e{i}") for i in range(6)])
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        # No crash; previous_retros is empty
        self.assertEqual(data["previous_retros"], [])


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


class TestDecisionTopicsWiring(_HookTestCase):
    """evaluate_flags receives decision topics extracted from events."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_decision_topics_suppress_flags(self):
        import retrospective

        decision = make_event(
            "decision",
            content="Adopted retro Try: kickoff exemption",
            topic="retro-try-kickoff-exemption",
        )
        code_event = make_event("status", content="wrote code", working_on=["foo.py"])
        filler = [make_event(content=f"f{i}") for i in range(55)]
        commit = make_event("commit", content="git commit")
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

        code_event = make_event("status", content="wrote code", working_on=["foo.py"])
        filler = [make_event(content=f"f{i}") for i in range(55)]
        commit = make_event("commit", content="git commit")
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


if __name__ == "__main__":
    unittest.main()
