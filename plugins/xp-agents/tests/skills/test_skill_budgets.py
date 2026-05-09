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

from conftest import _PLUGIN_ROOT

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
    "xp-story-close": 270,
    "xp-system-context": 30,
    "xp-work-selection": 190,
}


class TestSkillBudgets(unittest.TestCase):
    def test_every_skill_has_budget_entry(self):
        """Every shipped SKILL.md must have a budget entry. New skills must add one."""
        skills_dir = _PLUGIN_ROOT / "skills"
        on_disk = {p.parent.name for p in skills_dir.glob("*/SKILL.md")}
        missing = on_disk - set(SKILL_BUDGETS)
        extra = set(SKILL_BUDGETS) - on_disk
        self.assertFalse(
            missing,
            f"SKILL.md files without a SKILL_BUDGETS entry: {sorted(missing)}",
        )
        self.assertFalse(
            extra,
            f"SKILL_BUDGETS entries with no matching SKILL.md: {sorted(extra)}",
        )

    def test_no_skill_exceeds_its_budget(self):
        """Every SKILL.md must be at or below its budget."""
        skills_dir = _PLUGIN_ROOT / "skills"
        offenders: list[str] = []
        for skill_name, budget in SKILL_BUDGETS.items():
            skill_md = skills_dir / skill_name / "SKILL.md"
            actual = len(skill_md.read_text(encoding="utf-8").splitlines())
            if actual > budget:
                offenders.append(
                    f"{skill_name}/SKILL.md: {actual} lines (budget {budget})"
                )
        self.assertFalse(
            offenders,
            "SKILL.md files exceed their line budget:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
