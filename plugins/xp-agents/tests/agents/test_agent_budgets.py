#!/usr/bin/env python3
"""Per-agent .md character budgets.

Budget formula: `ratchet(measured, current, 10)` — see
`_budget_helpers.ratchet`. The calibration rule is `measured * 1.125` rounded
to the nearest 10, but a budget may only ever come DOWN: applied bare, that
rule RAISES any surface trimmed by less than 11.1%, handing back the headroom
the trim just bought. Entries that "hold" are exactly those.

The assertion fails at 98% of budget, not on breach. A surface at its cap
still passed under the old check, which is how nine skills, three agents and
one guide drifted to 98-100% of cap while every suite stayed green.

Adding a new agent: measure len(Path("agents/<name>.md").read_text()),
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

AGENT_BUDGETS: dict[str, int] = {
    "xp-close-reviewer": 8980,
    "xp-code-reviewer": 8550,
    "xp-housekeeper": 10080,
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
    "xp-sprint-reviewer": 4380,
    # Bumped 19640 -> 20370 for the surface `paths`/`command` template fields
    # plus the update-mode re-emit warning. A deliberate bump, not a ratchet:
    # `ratchet` only ever lowers, and the file sat at 99.3% of the old budget
    # once the two fields landed. The re-emit sentence is load-bearing —
    # update mode replaces the whole surfaces array, so without it a declared
    # value is deleted silently (TestSystemAnalyzerPromptMaxlengthSync pins
    # it). Trimmed first; measured 19507 after the trim.
    #
    # Bumped 20370 -> 20700 (story-017): the surface block gained the
    # propose-confirm-write step and the residue-surface rule. Deliberate, and
    # deliberately NOT paid for by trimming: nothing populates `paths`/
    # `command` unless this prose asks for them, so it is the only thing
    # between the whole surface chain and permanent dormancy — and the residue
    # rule specifically, because all-or-nothing selection means one unclaimed
    # path vetoes narrowing and makes every declared command inert. Measured
    # 20161 after the edit.
    "xp-system-analyzer": 20700,
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
