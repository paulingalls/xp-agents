#!/usr/bin/env python3
"""Tests for sprint_archive.py's archive() store function.

Mirrors test_execution_plan_store.py's TestArchive — sprint.json gets the
same archive-before-overwrite treatment plans already have.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase
from conftest import make_sprint_dict as _make_sprint


class TestArchive(_SMMTestCase):
    def test_archive_moves_to_sprints_dir(self):
        import sprint_archive

        sprint = _make_sprint()
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        archived_path = sprint_archive.archive(self.smm_dir)
        assert archived_path is not None
        self.assertFalse((self.smm_dir / "sprint.json").exists())
        self.assertTrue(archived_path.exists())
        self.assertTrue(archived_path.parent.name == "sprints")

    def test_archive_missing_file_returns_none(self):
        import sprint_archive

        result = sprint_archive.archive(self.smm_dir)
        self.assertIsNone(result)

    def test_archive_preserves_content(self):
        import sprint_archive

        sprint = _make_sprint(sprint_id="sprint-042")
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        archived_path = sprint_archive.archive(self.smm_dir)
        assert archived_path is not None
        loaded = json.loads(archived_path.read_text())
        self.assertEqual(loaded["sprint_id"], "sprint-042")
