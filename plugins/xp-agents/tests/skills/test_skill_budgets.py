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
    "xp-assign": 21020,
    "xp-end-session": 6440,
    # Bumped 8590 -> 8750: auto-merge condition 2 now pipes the close diff into
    # count-concerns via --diff-paths, plus the one-paragraph rule (what gets
    # dropped, and that an empty diff counts everything). Re-trimmed that
    # paragraph to a single sentence first; the full rationale lives once in
    # the shared close-pipeline reference, which the preload injects alongside.
    "xp-free-close": 8750,
    "xp-kickoff": 9020,
    # Bumped 10030 -> 10230: the skill gained an authored field (`schedules`)
    # and the writer path that reaches it (edit-milestone), and step 9 now states
    # the delivery-field refusal the CLI actually enforces. Re-trimmed first —
    # the `schedules` bullet is shorter than the one it replaced.
    "xp-plan": 10230,
    "xp-plan-close": 6140,
    "xp-quality-review": 8190,
    "xp-review-plan": 1020,
    "xp-scaffold-acceptance": 22810,
    "xp-schedule": 7070,
    "xp-sprint-close": 7540,
    "xp-sprint-review": 1850,
    "xp-sprint-start": 12560,
    "xp-stage-migration": 2940,
    # Bumped 12110 -> 12450 (story-025): condition 2 became a deterministic
    # count-concerns read (mirrors condition 1's count-classifications) and
    # Step 4.5b gained the close-cycle-id threading clause. Re-trimmed
    # surrounding prose to the minimum first.
    #
    # Bumped 12450 -> 12770: condition 2 now pipes the close diff into
    # count-concerns via --diff-paths, so an unrelated open concern filed in the
    # same window can no longer abort a clean close. The pipe plus the
    # three-line rule (what gets dropped, why HEAD is wrong here) does not fit
    # in the 21 chars that were left. Re-trimmed the note to three lines first —
    # the full rationale lives once in the shared close-pipeline reference,
    # which the preload injects alongside this skill.
    "xp-story-close": 12770,
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
