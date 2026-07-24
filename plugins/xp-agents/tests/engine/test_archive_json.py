#!/usr/bin/env python3
"""Tests for archive.py's archive_json() shared helper.

Covers the same-second collision guard that motivated extracting one
helper out of sprint_archive.archive() and execution_plan_store.archive().
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase

_FIXED_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FIXED_TS


class TestArchiveJson(_SMMTestCase):
    def test_same_second_collision_does_not_clobber(self):
        import archive

        with patch.object(archive, "datetime", _FixedDatetime):
            (self.smm_dir / "src.json").write_text("content A")
            first = archive.archive_json(self.smm_dir, "src.json", "things", "thing")
            assert first is not None
            self.assertEqual(first.name, "thing_20260101T120000.json")

            (self.smm_dir / "src.json").write_text("content B")
            second = archive.archive_json(self.smm_dir, "src.json", "things", "thing")
            assert second is not None
            self.assertEqual(second.name, "thing_20260101T120000-1.json")

            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(first.read_text(), "content A")
            self.assertEqual(second.read_text(), "content B")

    def test_missing_source_returns_none_and_creates_no_file(self):
        import archive

        result = archive.archive_json(self.smm_dir, "missing.json", "things", "thing")
        self.assertIsNone(result)
        things_dir = self.smm_dir / "things"
        self.assertEqual(list(things_dir.glob("*.json")), [])

    def test_uncontended_name_has_no_suffix(self):
        import archive

        (self.smm_dir / "src.json").write_text("content")
        dest = archive.archive_json(self.smm_dir, "src.json", "things", "thing")
        assert dest is not None
        self.assertNotIn("-", dest.stem.split("_", 1)[1])

    def test_failed_move_leaves_no_empty_placeholder(self):
        """A move that fails for any reason must clean up its O_EXCL claim.

        The claim is a 0-byte file with a real snapshot's name. Left behind, it
        reads as a valid archived sprint/plan to every later reader — and to
        the next same-second archive, which would then skip that name and file
        the real snapshot under a `-1` suffix beside the empty one.
        """
        import archive

        (self.smm_dir / "src.json").write_text("content")
        with (
            patch.object(archive.shutil, "move", side_effect=PermissionError("nope")),
            self.assertRaises(PermissionError),
        ):
            archive.archive_json(self.smm_dir, "src.json", "things", "thing")
        self.assertEqual(list((self.smm_dir / "things").glob("*.json")), [])
        self.assertTrue((self.smm_dir / "src.json").exists(), "source untouched")

    def test_exhaustion_raises_oserror(self):
        import archive

        with patch.object(archive, "datetime", _FixedDatetime):
            things_dir = self.smm_dir / "things"
            things_dir.mkdir(exist_ok=True)
            for collision in range(archive.MAX_COLLISIONS):
                suffix = "" if collision == 0 else f"-{collision}"
                (things_dir / f"thing_20260101T120000{suffix}.json").write_text("x")

            (self.smm_dir / "src.json").write_text("content")
            with self.assertRaises(OSError):
                archive.archive_json(self.smm_dir, "src.json", "things", "thing")


if __name__ == "__main__":
    unittest.main()
