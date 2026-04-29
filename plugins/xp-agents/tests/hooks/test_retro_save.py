#!/usr/bin/env python3
"""Tests for retrospective digest, save retrospective, save SMM, and compact log."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, file_write_status, make_event, tests_run_status


class TestRetroDigest(_HookTestCase):
    """Tests for retrospective digest helpers."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_digest_signal_events(self):
        """Decisions/concerns in signal_events, status excluded."""
        import retro_metrics

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow tests", severity="medium"),
            make_event("status", content="Wrote file", working_on=["f.py"]),
            make_event("status", content="More work", working_on=["g.py"]),
            make_event("customer_input", content="Please fix"),
        ]
        self._write_events(events)
        digest = retro_metrics._build_retro_digest(events, 0, {})
        signal_types = {e["type"] for e in digest["signal_events"]}
        self.assertIn("decision", signal_types)
        self.assertIn("concern", signal_types)
        self.assertIn("customer_input", signal_types)
        self.assertNotIn("status", signal_types)

    def test_digest_status_summary(self):
        """Correct counts for file_writes/test_runs/other."""
        import retro_metrics

        events = [
            file_write_status("src/app.ts"),
            file_write_status("src/util.ts"),
            tests_run_status(count=5),
            make_event(
                "status",
                content="Thinking about design",
                working_on=[],
            ),
        ]
        self._write_events(events)
        digest = retro_metrics._build_retro_digest(events, 0, {})
        ss = digest["status_summary"]
        self.assertEqual(ss["total"], 4)
        self.assertEqual(ss["file_writes"], 2)
        self.assertEqual(ss["test_runs"], 1)
        self.assertEqual(ss["other"], 1)

    def test_digest_concern_groups_dedup(self):
        """3 identical failure concerns -> 1 group with count=3."""
        import retro_metrics

        events = [
            make_event(
                "concern",
                content="Test failures detected: 2 failed (pytest)",
                severity="high",
            )
            for _ in range(3)
        ]
        self._write_events(events)
        digest = retro_metrics._build_retro_digest(events, 0, {})
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 3)

    def test_digest_concern_groups_unique(self):
        """3 different concerns -> 3 groups with count=1."""
        import retro_metrics

        events = [
            make_event("concern", content="Slow tests", severity="medium"),
            make_event("concern", content="Missing docs", severity="low"),
            make_event(
                "concern",
                content="Security issue",
                severity="high",
            ),
        ]
        self._write_events(events)
        digest = retro_metrics._build_retro_digest(events, 0, {})
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g["count"], 1)

    def test_digest_preserves_event_ids(self):
        """All signal event IDs present."""
        import retro_metrics

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow", severity="low"),
        ]
        self._write_events(events)
        digest = retro_metrics._build_retro_digest(events, 0, {})
        signal_ids = {e["id"] for e in digest["signal_events"]}
        for e in events:
            self.assertIn(e["id"], signal_ids)

    def test_normalize_concern_strips_numbers(self):
        """Numbers normalized for consistent grouping."""
        import retro_metrics

        k1 = retro_metrics._normalize_concern_content(
            "Test failures detected: 2 failed (pytest)"
        )
        k2 = retro_metrics._normalize_concern_content(
            "Test failures detected: 5 failed (pytest)"
        )
        self.assertEqual(k1, k2)

    def test_retro_input_uses_digest(self):
        """_build_retro_input should include digest keys."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event(
                "status",
                content="Wrote to f.py",
                working_on=["f.py"],
            ),
            make_event(
                "status",
                content="Tests: 5 passed, 0 failed",
                working_on=[],
            ),
            make_event("concern", content="Slow", severity="low"),
            make_event("customer_input", content="Fix it"),
        ]
        self._write_events(events)
        retro_input = retrospective._build_retro_input(events, 0, [])
        self.assertIn("digest", retro_input)
        digest = retro_input["digest"]
        self.assertIn("signal_events", digest)
        self.assertIn("status_summary", digest)
        self.assertIn("concern_groups", digest)


class TestSaveRetrospective(_HookTestCase):
    """Tests for save_retrospective.py helper script."""

    def setUp(self):
        super().setUp()
        # Create retrospectives directory (init.sh normally does this)
        (self.smm_dir / "retrospectives").mkdir(exist_ok=True)

    def _valid_kft(self) -> dict:
        return {
            "keep": [
                {
                    "content": "TDD discipline held",
                    "event_refs": ["abc123"],
                    "values": ["Feedback"],
                }
            ],
            "fix": [
                {
                    "content": "Housekeeping silent",
                    "event_refs": ["def456"],
                    "xp_value": "Communication",
                }
            ],
            "try": [
                {
                    "content": "Investigate housekeeping pipeline",
                    "event_refs": ["ghi789"],
                }
            ],
        }

    def test_valid_kft_creates_event_and_file(self):
        import save_retrospective

        result = save_retrospective.run(self._valid_kft(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("event_id", result)
        self.assertIn("retro_file", result)

        # Verify event in events.jsonl
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 1)
        ev = retro_events[0]
        self.assertEqual(len(ev["keep"]), 1)
        self.assertEqual(ev["keep"][0]["content"], "TDD discipline held")
        self.assertEqual(len(ev["fix"]), 1)
        self.assertEqual(ev["fix"][0]["xp_value"], "Communication")
        self.assertEqual(len(ev["try"]), 1)
        self.assertEqual(ev["try"][0]["content"], "Investigate housekeeping pipeline")
        self.assertIn("1 keeps, 1 fixes, 1 tries", ev["content"])

        # Verify retrospective file exists
        retro_file = Path(result["retro_file"])
        self.assertTrue(retro_file.exists())
        retro_data = json.loads(retro_file.read_text())
        self.assertIn("keep", retro_data)
        self.assertIn("fix", retro_data)
        self.assertIn("try", retro_data)
        self.assertIn("timestamp", retro_data)

    def test_missing_content_field_errors(self):
        import save_retrospective

        bad_kft = {"keep": [{"event_refs": ["abc"]}], "fix": [], "try": []}
        result = save_retrospective.run(bad_kft, smm_dir=self.smm_dir)
        self.assertIsNone(result)
        # No event should be written
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 0)

    def test_empty_arrays_succeeds(self):
        import save_retrospective

        empty_kft = {"keep": [], "fix": [], "try": []}
        result = save_retrospective.run(empty_kft, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 1)
        self.assertIn("0 keeps, 0 fixes, 0 tries", retro_events[0]["content"])

    def test_invalid_json_stdin(self):
        """When called as main with invalid JSON on stdin, should exit 1."""
        import save_retrospective

        result = save_retrospective.run(None, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_optional_analysis_notes(self):
        import save_retrospective

        kft = self._valid_kft()
        kft["analysis_notes"] = "Cross-session trend: housekeeping silent for 4 retros"
        result = save_retrospective.run(kft, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

        retro_file = Path(result["retro_file"])
        retro_data = json.loads(retro_file.read_text())
        self.assertEqual(
            retro_data["analysis_notes"],
            "Cross-session trend: housekeeping silent for 4 retros",
        )


class TestSaveRetrospectiveParams(_HookTestCase):
    """M12: parameterized agent, prefix, and cleanup file."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir(exist_ok=True)

    def _valid_kft(self) -> dict:
        return {
            "keep": [{"content": "Good"}],
            "fix": [],
            "try": [],
        }

    def test_custom_agent_id(self):
        import save_retrospective

        result = save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
            agent_id="xp-sprint-retro",
        )
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro["agent_id"], "xp-sprint-retro")

    def test_custom_prefix(self):
        import save_retrospective

        result = save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
            prefix="Sprint retrospective",
        )
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertIn("Sprint retrospective", retro["content"])

    def test_custom_cleanup_file(self):
        import save_retrospective

        cleanup = self.smm_dir / ".sprint-retro-input.json"
        cleanup.write_text("{}")
        save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
            cleanup_file=".sprint-retro-input.json",
        )
        self.assertFalse(cleanup.exists())

    def test_defaults_unchanged(self):
        """Default agent_id and prefix match existing session retro behavior."""
        import save_retrospective

        (self.smm_dir / ".retro-input.json").write_text("{}")
        result = save_retrospective.run(self._valid_kft(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro["agent_id"], "xp-retrospective")
        self.assertIn("Session retrospective", retro["content"])
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())


class TestSaveRetrospectiveRetroKind(_HookTestCase):
    """M1a: --retro-kind flag writes metadata.action discriminator."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir(exist_ok=True)

    def _valid_kft(self) -> dict:
        return {
            "keep": [{"content": "Good"}],
            "fix": [],
            "try": [],
        }

    def test_retro_kind_session_writes_session_action(self):
        """--retro-kind session writes metadata.action=session_retro_done."""
        import save_retrospective

        result = save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
            retro_kind="session",
        )
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro.get("metadata", {}).get("action"), "session_retro_done")

    def test_retro_kind_sprint_writes_sprint_action(self):
        """--retro-kind sprint puts metadata.action=sprint_retro_done on retro event."""
        import save_retrospective

        result = save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
            retro_kind="sprint",
        )
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro.get("metadata", {}).get("action"), "sprint_retro_done")

    def test_retro_kind_default_is_session(self):
        """No retro_kind argument defaults to session for backwards compat."""
        import save_retrospective

        result = save_retrospective.run(
            self._valid_kft(),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro.get("metadata", {}).get("action"), "session_retro_done")

    def test_retro_kind_constants_exist(self):
        """event_schema.py exposes RETRO_ACTION_SESSION_DONE/SPRINT_DONE constants."""
        import event_schema

        self.assertEqual(event_schema.RETRO_ACTION_SESSION_DONE, "session_retro_done")
        self.assertEqual(event_schema.RETRO_ACTION_SPRINT_DONE, "sprint_retro_done")


class TestSaveRetrospectiveSchemaEnforcement(_HookTestCase):
    """save_retrospective.run should reject retros that fail schema validation."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir(exist_ok=True)

    def test_five_tries_rejected(self):
        import save_retrospective

        kft = {
            "keep": [{"content": "Good"}],
            "fix": [],
            "try": [{"content": f"Try {i}"} for i in range(5)],
        }
        result = save_retrospective.run(kft, smm_dir=self.smm_dir)
        self.assertIsNone(result)
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 0)

    def test_over_budget_keep_rejected(self):
        import save_retrospective

        kft = {"keep": [{"content": "x" * 251}], "fix": [], "try": []}
        result = save_retrospective.run(kft, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_within_budget_passes(self):
        import save_retrospective

        kft = {
            "keep": [{"content": "x" * 250}],
            "fix": [{"content": "x" * 300}],
            "try": [{"content": "x" * 300}],
        }
        result = save_retrospective.run(kft, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        events = self._read_events()
        retro_events = [e for e in events if e["type"] == "retrospective"]
        self.assertEqual(len(retro_events), 1)


if __name__ == "__main__":
    unittest.main()
