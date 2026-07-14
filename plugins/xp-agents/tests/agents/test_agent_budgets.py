#!/usr/bin/env python3
"""Per-agent .md character budgets.

Sprint-075 token audit (M-2): each agents/*.md is capped at roughly
trimmed_size * 1.125 (rounded to nearest 10). Growth past the budget
fails this test, forcing either a deliberate budget bump or a re-trim.

Adding a new agent: measure len(Path("agents/<name>.md").read_text()),
compute round(chars * 1.125 / 10) * 10, add the entry below.
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
    "xp-close-reviewer": 8980,
    "xp-code-reviewer": 8550,
    "xp-housekeeper": 11230,
    "xp-plan-reviewer": 21940,
    # Bumped 21770 -> 22050 for the --retro-kind sprint instruction. This agent
    # is the ONLY caller of save_retrospective.py, so without that instruction
    # the sprint-retro completion marker has no reachable producer and every
    # sprint's commits stay pinned in the log forever. Load-bearing prose, not
    # padding — deliberate bump per this module's docstring.
    #
    # Bumped 22050 -> 23100 for the plan_schedule check in the aging-debt
    # escalation ladder. No code computes debt age or emits "unresolved xN" —
    # the ladder is prose and the model counts the sessions, so the prompt is
    # the only place the "already scheduled, do not escalate" rule can live
    # (TestPlanScheduleProseContract pins it). Re-trimmed first: the field
    # description and the rule were cut ~670 chars before this bump.
    "xp-retrospective": 23100,
    "xp-sprint-reviewer": 4660,
    "xp-system-analyzer": 19640,
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
