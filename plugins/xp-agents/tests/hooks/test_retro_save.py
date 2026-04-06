#!/usr/bin/env python3
"""Tests for retrospective digest, save retrospective, save SMM, and compact log."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


class TestRetroDigest(_HookTestCase):
    """Tests for retrospective digest helpers."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_digest_signal_events(self):
        """Decisions/concerns in signal_events, status excluded."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow tests", severity="medium"),
            make_event("status", content="Wrote file", working_on=["f.py"]),
            make_event("status", content="More work", working_on=["g.py"]),
            make_event("customer_input", content="Please fix"),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0, set())
        signal_types = {e["type"] for e in digest["signal_events"]}
        self.assertIn("decision", signal_types)
        self.assertIn("concern", signal_types)
        self.assertIn("customer_input", signal_types)
        self.assertNotIn("status", signal_types)

    def test_digest_status_summary(self):
        """Correct counts for file_writes/test_runs/other."""
        import retrospective

        events = [
            make_event(
                "status",
                content="Wrote to src/app.ts",
                working_on=["src/app.ts"],
            ),
            make_event(
                "status",
                content="Wrote to src/util.ts",
                working_on=["src/util.ts"],
            ),
            make_event(
                "status",
                content="Tests: 5 passed, 0 failed (pytest)",
                working_on=[],
            ),
            make_event(
                "status",
                content="Thinking about design",
                working_on=[],
            ),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0, set())
        ss = digest["status_summary"]
        self.assertEqual(ss["total"], 4)
        self.assertEqual(ss["file_writes"], 2)
        self.assertEqual(ss["test_runs"], 1)
        self.assertEqual(ss["other"], 1)

    def test_digest_concern_groups_dedup(self):
        """3 identical failure concerns -> 1 group with count=3."""
        import retrospective

        events = [
            make_event(
                "concern",
                content="Test failures detected: 2 failed (pytest)",
                severity="high",
            )
            for _ in range(3)
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0, set())
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 3)

    def test_digest_concern_groups_unique(self):
        """3 different concerns -> 3 groups with count=1."""
        import retrospective

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
        digest = retrospective._build_retro_digest(events, 0, set())
        groups = digest["concern_groups"]
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g["count"], 1)

    def test_digest_preserves_event_ids(self):
        """All signal event IDs present."""
        import retrospective

        events = [
            make_event("decision", content="Use REST", topic="api"),
            make_event("concern", content="Slow", severity="low"),
        ]
        self._write_events(events)
        digest = retrospective._build_retro_digest(events, 0, set())
        signal_ids = {e["id"] for e in digest["signal_events"]}
        for e in events:
            self.assertIn(e["id"], signal_ids)

    def test_normalize_concern_strips_numbers(self):
        """Numbers normalized for consistent grouping."""
        import retrospective

        k1 = retrospective._normalize_concern_content(
            "Test failures detected: 2 failed (pytest)"
        )
        k2 = retrospective._normalize_concern_content(
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


class TestSaveSMM(_HookTestCase):
    """Tests for save_smm.py helper script."""

    def setUp(self):
        super().setUp()
        # Add skill scripts to path so we can import save_smm
        skill_scripts = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-housekeeping"
            / "scripts"
        )
        if str(skill_scripts) not in sys.path:
            sys.path.insert(0, str(skill_scripts))

    def test_writes_smm_file(self):
        """save_smm.run() writes markdown content to SHARED_MENTAL_MODEL.md."""
        import save_smm

        content = "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        save_smm.run(content, smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        self.assertTrue(smm_file.exists())
        self.assertEqual(smm_file.read_text(), content)

    def test_updates_curation_watermark(self):
        """save_smm.run() updates .curation-watermark with event count."""
        import save_smm

        # Seed some events
        self._write_events(
            [
                make_event("goal", content="Ship v1"),
                make_event("concern", content="No tests"),
            ]
        )
        save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        import materialize as _mat

        wm = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm["event_count"], 2)
        self.assertEqual(wm["agent_id"], "xp-housekeeping")

    def test_overwrites_existing_smm(self):
        """save_smm.run() overwrites an existing SHARED_MENTAL_MODEL.md."""
        import save_smm

        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text("old content")
        save_smm.run("new content", smm_dir=self.smm_dir)
        self.assertEqual(smm_file.read_text(), "new content")

    def test_file_permissions(self):
        """Written SMM file has mode 0o600."""
        import save_smm

        save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        mode = smm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_empty_content_writes_empty_file(self):
        """Empty string input produces an empty file."""
        import save_smm

        save_smm.run("", smm_dir=self.smm_dir)
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        self.assertTrue(smm_file.exists())
        self.assertEqual(smm_file.read_text(), "")

    # TestCompactLog removed — compact_log.py deleted in M5 cleanup.
    # Compaction is tested via compact.compact_after_curation() in
    # tests/engine/test_compact_curation.py.


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


if __name__ == "__main__":
    unittest.main()
