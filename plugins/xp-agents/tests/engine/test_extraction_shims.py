#!/usr/bin/env python3
"""Smoke tests pinning the extraction surfaces this story had to carve out.

Both extractions were forced by the file-size cap, not chosen: sprint_save.py
sat inside its frozen band and sprint_store.py crossed the hard cap. Each keeps
its historical import path via a re-export, and that shim is what the rest of
the tree still imports — so it is pinned here, at collection time, rather than
discovered as a pile of downstream failures.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestSisterLayoutExtractionSurface(unittest.TestCase):
    def test_shim_imports_from_sprint_save(self):
        import sprint_save

        self.assertTrue(callable(sprint_save._resolve_layout))
        self.assertTrue(callable(sprint_save._coerce_overrides))

    def test_direct_imports_from_module(self):
        """Extraction is real, not a flat-namespace alias."""
        from sister_layout import _coerce_overrides, _resolve_layout

        self.assertTrue(callable(_resolve_layout))
        self.assertTrue(callable(_coerce_overrides))


class TestSprintTransitionsExtractionSurface(unittest.TestCase):
    def test_shim_imports_from_sprint_store(self):
        import sprint_store

        self.assertTrue(callable(sprint_store.update_story_status))
        self.assertTrue(callable(sprint_store.update_story_status_if))

    def test_direct_imports_from_module(self):
        """Extraction is real, not a flat-namespace alias."""
        from sprint_transitions import (
            _write_story_status,
            update_story_status,
            update_story_status_if,
        )

        self.assertTrue(callable(_write_story_status))
        self.assertTrue(callable(update_story_status))
        self.assertTrue(callable(update_story_status_if))


if __name__ == "__main__":
    unittest.main()
