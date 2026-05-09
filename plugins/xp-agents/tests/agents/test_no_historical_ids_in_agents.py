#!/usr/bin/env python3
"""agent .md files stay project-generic — no 12-hex SMM event IDs.

Sprint-075 token audit (M-2): catches re-introduction of 12-hex
decision/concern/event IDs in shipped agent prose. Mirrors
test_no_historical_ids_in_skills.py.

Scope: 12-hex IDs only. story-NNN / sprint-NNN are pedagogical
placeholders in JSON template examples and are deliberately not
matched here (mirrors test_no_project_local_ids.py exclusion).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, assert_no_12hex_ids_in_md


class TestNoHistoricalIDsInAgents(unittest.TestCase):
    def test_no_12hex_ids_in_agent_md(self):
        assert_no_12hex_ids_in_md(self, _PLUGIN_ROOT / "agents", "*.md", "agents/*.md")


if __name__ == "__main__":
    unittest.main()
