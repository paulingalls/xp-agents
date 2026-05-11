"""Tests for marker_names.py — pin every dotfile constant is well-formed.

Constant invariants: non-empty string, starts with `.` (dotfile convention),
no whitespace. Template constants (with `{name}` / `{agent_id}` placeholders)
also satisfy these — the placeholder substring is non-whitespace.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import marker_names


class TestDotfileMarkerConstants(unittest.TestCase):
    """Every centralized dotfile constant is a well-formed marker name."""

    CONSTANT_NAMES = (
        "LINT_WARNED",
        "SPRINT_RETRO_INPUT",
        "CURATION_INPUT",
        "COORDINATION_JSON",
        "COORDINATION_LOCK",
        "TEAMMATE_REPORT",
        "STORY_ASSIGNMENT",
    )

    def test_each_constant_is_well_formed_dotfile(self):
        for name in self.CONSTANT_NAMES:
            with self.subTest(constant=name):
                value = getattr(marker_names, name)
                self.assertIsInstance(value, str)
                self.assertTrue(value, "must be non-empty")
                self.assertTrue(value.startswith("."), f"{value!r} must start with '.'")
                self.assertNotIn(" ", value, f"{value!r} must not contain whitespace")


if __name__ == "__main__":
    unittest.main()
