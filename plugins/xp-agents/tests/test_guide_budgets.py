#!/usr/bin/env python3
"""Per-guide character budgets for top-level *.md guides.

Sister to skills/test_skill_budgets.py and agents/test_agent_budgets.py:
the three top-level guides preload into context every session/subagent
(XP_VALUES on every SessionStart + SubagentStart) so growth costs tokens
on every fire. Budget formula: round(chars * 1.125 / 10) * 10.

Adding a new top-level guide: measure len(Path("<name>.md").read_text()),
compute round(chars * 1.125 / 10) * 10, add the entry below.
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
    "XP_VALUES": 1150,
    "PROCESS_GUIDE": 8200,
    "TEAMMATE_GUIDE": 4240,
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
