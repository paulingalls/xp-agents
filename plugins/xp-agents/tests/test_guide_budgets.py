#!/usr/bin/env python3
"""Per-guide line budgets for top-level *.md (XP_VALUES, PROCESS_GUIDE, TEAMMATE_GUIDE).

Sister to skills/test_skill_budgets.py and agents/test_agent_budgets.py:
the three top-level guides preload into context every session/subagent
(XP_VALUES on every SessionStart + SubagentStart) so growth costs tokens
on every fire. Budget formula: round(trimmed_lines * 1.125 / 10) * 10.

Adding a new top-level guide: measure wc -l, compute budget, add entry.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import (
    _PLUGIN_ROOT,
    assert_md_budgets_match,
    assert_md_under_budgets,
    assert_no_12hex_ids_in_md,
)

GUIDE_BUDGETS: dict[str, int] = {
    "XP_VALUES": 20,
    "PROCESS_GUIDE": 100,
    "TEAMMATE_GUIDE": 60,
}

_LABEL = "<plugin>/*.md"


class TestGuideBudgets(unittest.TestCase):
    def test_every_guide_has_budget_entry(self):
        assert_md_budgets_match(self, _PLUGIN_ROOT, "*.md", GUIDE_BUDGETS, _LABEL)

    def test_no_guide_exceeds_its_budget(self):
        assert_md_under_budgets(self, _PLUGIN_ROOT, "*.md", GUIDE_BUDGETS, _LABEL)

    def test_no_12hex_ids_in_guide_md(self):
        assert_no_12hex_ids_in_md(self, _PLUGIN_ROOT, "*.md", _LABEL)


if __name__ == "__main__":
    unittest.main()
