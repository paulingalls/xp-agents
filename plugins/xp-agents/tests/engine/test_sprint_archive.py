#!/usr/bin/env python3
"""Tests for sprint_archive.py's archive() store function.

Mirrors test_execution_plan_store.py's TestArchive — sprint.json gets the
same archive-before-overwrite treatment plans already have.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase
from conftest import make_sprint_dict as _make_sprint

_FIXED_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FIXED_TS


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

    def test_same_second_archives_do_not_clobber(self):
        import archive
        import sprint_archive

        with patch.object(archive, "datetime", _FixedDatetime):
            first_sprint = _make_sprint(sprint_id="sprint-001")
            (self.smm_dir / "sprint.json").write_text(json.dumps(first_sprint))
            first = sprint_archive.archive(self.smm_dir)
            assert first is not None

            second_sprint = _make_sprint(sprint_id="sprint-002")
            (self.smm_dir / "sprint.json").write_text(json.dumps(second_sprint))
            second = sprint_archive.archive(self.smm_dir)
            assert second is not None

            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(json.loads(first.read_text())["sprint_id"], "sprint-001")
            self.assertEqual(json.loads(second.read_text())["sprint_id"], "sprint-002")
