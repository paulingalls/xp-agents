#!/usr/bin/env python3
"""Per-skill SKILL.md character budgets.

Budget formula: `ratchet(measured, current, 10)` — see
`_budget_helpers.ratchet`. The calibration rule is `measured * 1.125` rounded
to the nearest 10, but a budget may only ever come DOWN: applied bare, that
rule RAISES any surface trimmed by less than 11.1%, handing back the headroom
the trim just bought. Entries that "hold" are exactly those.

The assertion fails at 98% of budget, not on breach. A surface at its cap
still passed under the old check, which is how nine skills, three agents and
one guide drifted to 98-100% of cap while every suite stayed green.

Adding a new skill: measure len(Path("skills/<name>/SKILL.md").read_text()),
apply `ratchet(chars, <a first budget>, 10)`, add the entry below.
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
    "xp-accept": 15400,
    "xp-assign": 20700,
    "xp-end-session": 5810,
    # Bumped 8590 -> 8750: auto-merge condition 2 now pipes the close diff into
    # count-concerns via --diff-paths, plus the one-paragraph rule (what gets
    # dropped, and that an empty diff counts everything). Re-trimmed that
    # paragraph to a single sentence first; the full rationale lives once in
    # the shared close-pipeline reference, which the preload injects alongside.
    # story-017 rewrote condition 3 to consume the resolved `### GATE_COMMANDS`
    # set (aggregation + the collapse note) and NOT bumped: measured 8048 =
    # 92.0%, so the existing budget absorbed it. Recorded because the next
    # editor's question is "how much is left", and the answer is ~700 chars —
    # a deliberate non-bump is as much a measurement as a bump.
    "xp-free-close": 8750,
    "xp-kickoff": 9020,
    # Bumped 10030 -> 10230: the skill gained an authored field (`schedules`)
    # and the writer path that reaches it (edit-milestone), and step 9 now states
    # the delivery-field refusal the CLI actually enforces. Re-trimmed first —
    # the `schedules` bullet is shorter than the one it replaced.
    "xp-plan": 10230,
    "xp-plan-close": 5670,
    "xp-quality-review": 6720,
    "xp-review-plan": 990,
    "xp-scaffold-acceptance": 20940,
    # First budget for the finished surface: measured 7853, formula 8830. The
    # registration increment carried 810, calibrated on a 720-char skeleton
    # that is not this surface — re-derived rather than nudged, since a ratchet
    # can only ever lower and would have pinned the skill to its skeleton.
    "xp-scaffold-worktree": 8830,
    "xp-schedule": 6710,
    "xp-sprint-close": 7540,
    "xp-sprint-review": 1420,
    "xp-sprint-start": 12560,
    "xp-stage-migration": 2420,
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
    #
    # Bumped 12770 -> 12960 (story-016): condition 3 stopped naming
    # TEST_COMMAND directly and now consumes the `### GATE_COMMANDS` set the
    # preload resolved (surface-scoped, else the full command). The two
    # load-bearing sentences are the ones that cost the chars: "do not
    # re-derive the choice here" and the never-run-nothing invariant. Both
    # guard an AUTO-merge, and dropping either re-opens the vacuous-hold shape
    # conditions 1 and 2 were converted away from. Re-trimmed first: the first
    # draft measured 12700, trimmed to 12515, which still sat exactly on the
    # 98% band.
    #
    # Review then spent 147 of the 445 chars that bump bought, naming the cwd
    # condition 3's commands run from (the teammate path's checkout holds
    # neither the story nor the Step 5c fixes). Measured 12662 = 97.7%: the
    # bump is SPENT, 38 chars from the band. The next clause here trims one
    # first — do not read the remainder as headroom.
    "xp-story-close": 12960,
    "xp-system-context": 1070,
    "xp-work-selection": 8700,
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
