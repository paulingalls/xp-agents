#!/usr/bin/env python3
"""SKILL.md files stay project-generic — no 12-hex SMM event IDs.

Sprint-074 token audit: shipped SKILL.md prose accumulated references
to specific decision/concern/event IDs (12-hex) over time. This test
catches re-introduction.

Scope: 12-hex IDs only. story-NNN / sprint-NNN are pedagogical
placeholders in JSON template examples and are deliberately not
matched here (mirrors test_no_project_local_ids.py exclusion).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, assert_no_12hex_ids_in_md


class TestNoHistoricalIDsInSkills(unittest.TestCase):
    def test_no_12hex_ids_in_skill_md(self):
        assert_no_12hex_ids_in_md(
            self, _PLUGIN_ROOT / "skills", "*/SKILL.md", "SKILL.md"
        )


if __name__ == "__main__":
    unittest.main()
