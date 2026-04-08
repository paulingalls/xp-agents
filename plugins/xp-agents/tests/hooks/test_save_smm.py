#!/usr/bin/env python3
"""Tests for save_smm.py helper script (xp-housekeeping skill)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


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
            save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        mock_compact.assert_called_once_with(self.smm_dir)

    def test_compaction_failure_does_not_fail_write(self):
        """If compaction fails, save_smm should still succeed (write is primary)."""
        from unittest.mock import patch

        import save_smm

        target = "save_smm.compact.compact_after_curation"
        with patch(target, side_effect=OSError("boom")):
            save_smm.run("# SMM\n", smm_dir=self.smm_dir)
        # Write should have succeeded
        self.assertTrue((self.smm_dir / "SHARED_MENTAL_MODEL.md").exists())


if __name__ == "__main__":
    unittest.main()
