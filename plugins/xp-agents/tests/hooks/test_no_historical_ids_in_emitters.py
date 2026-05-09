#!/usr/bin/env python3
"""Emitter scripts stay project-generic — no 12-hex SMM event IDs.

Sprint-077 (M-3 sister guard): pairs with the per-emitter byte budget
(test_injection_budgets.py) so the emitter audit-debt has the same
two-guard shape as M-1 (skills) and M-2 (agents). Catches re-introduction
of 12-hex decision/concern/event IDs in shipped script docstrings/comments.

Scope: 12-hex IDs only. story-NNN / sprint-NNN are pedagogical
placeholders and are deliberately not matched here (mirrors
test_no_historical_ids_in_skills.py exclusion).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, assert_no_12hex_ids_in_md


class TestNoHistoricalIDsInEmitters(unittest.TestCase):
    def test_no_12hex_ids_in_emitter_py(self):
        assert_no_12hex_ids_in_md(
            self, _PLUGIN_ROOT / "scripts", "*.py", "scripts/*.py emitter"
        )


if __name__ == "__main__":
    unittest.main()
