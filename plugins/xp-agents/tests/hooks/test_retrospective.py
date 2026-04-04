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
        import retrospective

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_counts_different_files(self):
        """3 different files between tests should count as 3."""
        import retrospective

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/db.py"),
            self._make_write_status("src/api.py"),
            self._make_test_status(),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_resets_on_test_run(self):
        """Unique file set resets after each test run."""
        import retrospective

        events = [
            self._make_write_status("src/app.py"),
            self._make_write_status("src/db.py"),
            self._make_test_status(),
            self._make_write_status("src/api.py"),
            self._make_test_status(),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_excludes_test_files(self):
        """Test file writes should not count."""
        import retrospective

        events = [
            self._make_write_status("tests/test_app.py"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_excludes_non_code_files(self):
        """Non-code files (md, json, etc) should not count."""
        import retrospective

        events = [
            self._make_write_status("README.md"),
            self._make_write_status("config.json"),
            self._make_write_status("src/app.py"),
            self._make_test_status(),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)


class TestTriageCounting(unittest.TestCase):
    """Tests for commits_without_triage counting in _build_honesty_signals."""

    def test_code_commit_without_triage_counted(self):
        """Code commit without preceding triage is counted as untriaged."""
        import retrospective

        events = [
            make_event(
                "status",
                content="Committed: Add feature",
                metadata={"code_commit": True},
            ),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 1)

    def test_code_commit_with_triage_not_counted(self):
        """Code commit preceded by triage is not counted as untriaged."""
        import retrospective

        events = [
            make_event(
                "status",
                content="Security triage started — reviewing staged changes",
            ),
            make_event(
                "status",
                content="Committed: Add feature",
                metadata={"code_commit": True},
            ),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 0)

    def test_non_code_commit_without_triage_not_counted(self):
        """Non-code commit (docs-only) without triage is NOT counted as untriaged."""
        import retrospective

        events = [
            make_event(
                "status",
                content="Committed: Update docs",
                metadata={"code_commit": False},
            ),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 0)

    def test_legacy_commit_without_metadata_counted(self):
        """Legacy commit event without metadata is counted (backward compat)."""
        import retrospective

        events = [
            make_event("status", content="Committed: Old commit"),
        ]
        signals = retrospective._build_honesty_signals(events)
        self.assertEqual(signals["commits_without_triage"], 1)


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
        self.assertNotIn(c1["id"][:8], signal_ids)
        # Unresolved concern included
        self.assertIn(c2["id"][:8], signal_ids)

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
