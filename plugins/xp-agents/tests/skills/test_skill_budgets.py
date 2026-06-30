#!/usr/bin/env python3
"""Per-skill SKILL.md character budgets.

Budgets enforce token discipline post-sprint-074 audit: each SKILL.md
file is capped at roughly trimmed_size * 1.125 (rounded to nearest 10).
Growth past the budget fails this test, forcing either a deliberate
budget bump or a re-trim.

Adding a new skill: measure len(Path("skills/<name>/SKILL.md").read_text()),
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

SKILL_BUDGETS: dict[str, int] = {
    "xp-accept": 15310,
    "xp-assign": 10360,
    "xp-end-session": 6440,
    "xp-free-close": 8590,
    "xp-kickoff": 9020,
    "xp-plan": 10030,
    "xp-plan-close": 6140,
    "xp-quality-review": 8190,
    "xp-review-plan": 1020,
    "xp-scaffold-acceptance": 22810,
    "xp-schedule": 5860,
    "xp-sprint-close": 7540,
    "xp-sprint-review": 1850,
    "xp-sprint-start": 12560,
    "xp-stage-migration": 2940,
    "xp-story-close": 12110,
    "xp-system-context": 1250,
    "xp-work-selection": 8820,
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
