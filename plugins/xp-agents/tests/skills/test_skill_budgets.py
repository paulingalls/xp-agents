#!/usr/bin/env python3
"""Per-skill SKILL.md line budgets.

Budgets enforce token discipline post-sprint-074 audit: each SKILL.md
file is capped at roughly trimmed_size * 1.125 (rounded to nearest 10).
Growth past the budget fails this test, forcing either a deliberate
budget bump or a re-trim.

Adding a new skill: measure wc -l on the new SKILL.md, compute
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

SKILL_BUDGETS: dict[str, int] = {
    "xp-accept": 300,
    "xp-assign": 200,
    "xp-end-session": 130,
    "xp-free-close": 140,
    "xp-kickoff": 180,
    "xp-plan": 210,
    "xp-plan-close": 140,
    "xp-quality-review": 110,
    "xp-review-plan": 20,
    "xp-scaffold-acceptance": 450,
    "xp-sprint-close": 130,
    "xp-sprint-review": 30,
    "xp-sprint-start": 220,
    "xp-stage-migration": 60,
    "xp-story-close": 270,
    "xp-system-context": 30,
    "xp-work-selection": 190,
}

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_LABEL = "skills/*/SKILL.md"


class TestSkillBudgets(unittest.TestCase):
    def test_every_skill_has_budget_entry(self):
        assert_md_budgets_match(self, _SKILLS_DIR, "*/SKILL.md", SKILL_BUDGETS, _LABEL)

    def test_no_skill_exceeds_its_budget(self):
        assert_md_under_budgets(self, _SKILLS_DIR, "*/SKILL.md", SKILL_BUDGETS, _LABEL)


if __name__ == "__main__":
    unittest.main()
