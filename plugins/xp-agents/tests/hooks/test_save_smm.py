#!/usr/bin/env python3
"""Tests for save_smm.py helper script (xp-housekeeping skill).

save_smm.run() now accepts JSON content, validates against smm_schema,
and writes shared_mental_model.json atomically.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import smm_schema
import smm_store
from conftest import _HookTestCase, make_event


def _valid_smm_json(**overrides) -> str:
    """Build a valid SMM JSON string."""
    data = smm_schema.empty_smm()
    data.update(overrides)
    return json.dumps(data)


def _smm_with_intent(content: str = "Ship v1") -> str:
    """Build an SMM JSON with one intent entry."""
    import uuid

    data = smm_schema.empty_smm()
    data["intent"] = [
        {
            "id": str(uuid.uuid4()),
            "content": content,
            "source": "seed",
            "ts": "2026-01-01T00:00:00+00:00",
            "type": "goal",
        }
    ]
    return json.dumps(data)


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
        """save_smm.run() writes JSON content to shared_mental_model.json."""
        import save_smm

        content = _smm_with_intent("Ship v1")
        save_smm.run(content, smm_dir=self.smm_dir)
        smm_file = self.smm_dir / smm_store.SMM_FILENAME
        self.assertTrue(smm_file.exists())
        data = json.loads(smm_file.read_text())
        self.assertEqual(data["intent"][0]["content"], "Ship v1")

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
        save_smm.run(_valid_smm_json(), smm_dir=self.smm_dir)
        import materialize as _mat

        wm = _mat.read_curation_watermark(self.smm_dir)
        self.assertEqual(wm["event_count"], 2)
        self.assertEqual(wm["agent_id"], "xp-housekeeping")

    def test_overwrites_existing_smm(self):
        """save_smm.run() overwrites an existing shared_mental_model.json."""
        import save_smm

        smm_store.save_smm(self.smm_dir, smm_schema.empty_smm())
        save_smm.run(_smm_with_intent("new goal"), smm_dir=self.smm_dir)
        data = smm_store.load_smm(self.smm_dir)
        self.assertEqual(data["intent"][0]["content"], "new goal")

    def test_file_permissions(self):
        """Written SMM file has mode 0o600."""
        import save_smm

        save_smm.run(_valid_smm_json(), smm_dir=self.smm_dir)
        smm_file = self.smm_dir / smm_store.SMM_FILENAME
        mode = smm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_rejects_invalid_json(self):
        """Non-JSON input raises JSONDecodeError."""
        import save_smm

        with self.assertRaises(json.JSONDecodeError):
            save_smm.run("not json", smm_dir=self.smm_dir)

    def test_rejects_invalid_schema(self):
        """JSON that fails schema validation raises ValueError."""
        import save_smm

        with self.assertRaises(ValueError):
            save_smm.run('{"bad": "schema"}', smm_dir=self.smm_dir)

    def test_triggers_compaction(self):
        """save_smm.run() compacts the event log after writing and updating watermark.

        Ensures compaction happens regardless of whether housekeeping runs
        forked or inline — save_smm.py is the single place state changes.
        """
        from unittest.mock import patch

        import save_smm

        self._write_events([make_event("goal", content="Ship v1")])
        target = "save_smm.compact.compact_after_curation"
        with patch(target) as mock_compact:
            save_smm.run(_valid_smm_json(), smm_dir=self.smm_dir)
        mock_compact.assert_called_once_with(self.smm_dir)

    def test_compaction_failure_does_not_fail_write(self):
        """If compaction fails, save_smm should still succeed (write is primary)."""
        from unittest.mock import patch

        import save_smm

        target = "save_smm.compact.compact_after_curation"
        with patch(target, side_effect=OSError("boom")):
            save_smm.run(_valid_smm_json(), smm_dir=self.smm_dir)
        # Write should have succeeded
        self.assertTrue((self.smm_dir / smm_store.SMM_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
