#!/usr/bin/env python3
"""Smoke test pinning the extraction surface for sister_layout.

Written BEFORE the extraction out of sprint_save.py so cascade breakage shows
up at collection time rather than as a pile of downstream failures. The two
existing sister-test suites reach these through `sprint_save._resolve_layout`,
so the shim leg is what keeps them working.
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


if __name__ == "__main__":
    unittest.main()
