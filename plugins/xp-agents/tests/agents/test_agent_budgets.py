#!/usr/bin/env python3
"""Per-agent .md line budgets.

Sprint-075 token audit (M-2): each agents/*.md is capped at roughly
trimmed_size * 1.125 (rounded to nearest 10). Growth past the budget
fails this test, forcing either a deliberate budget bump or a re-trim.

Adding a new agent: measure wc -l on the new agent .md, compute
round(lines * 1.125 / 10) * 10, add the entry below.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    _PLUGIN_ROOT,
    assert_md_budgets_match,
    assert_md_under_budgets,
)

AGENT_BUDGETS: dict[str, int] = {
    "xp-close-reviewer": 140,
    "xp-code-reviewer": 90,
    "xp-housekeeper": 220,
    "xp-plan-reviewer": 180,
    "xp-retrospective": 250,
    "xp-sprint-reviewer": 80,
    "xp-system-analyzer": 260,
}

_AGENTS_DIR = _PLUGIN_ROOT / "agents"
_LABEL = "agents/*.md"


class TestAgentBudgets(unittest.TestCase):
    def test_every_agent_has_budget_entry(self):
        assert_md_budgets_match(self, _AGENTS_DIR, "*.md", AGENT_BUDGETS, _LABEL)

    def test_no_agent_exceeds_its_budget(self):
        assert_md_under_budgets(self, _AGENTS_DIR, "*.md", AGENT_BUDGETS, _LABEL)


if __name__ == "__main__":
    unittest.main()
