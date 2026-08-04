#!/usr/bin/env python3
"""Per-guide character budgets for top-level *.md guides.

Sister to skills/test_skill_budgets.py and agents/test_agent_budgets.py:
the three top-level guides preload into context every session/subagent
(XP_VALUES on every SessionStart + SubagentStart) so growth costs tokens
on every fire.

Budget formula: `ratchet(measured, current, 10)` — see
`_budget_helpers.ratchet`. The calibration rule is `measured * 1.125` rounded
to the nearest 10, but a budget may only ever come DOWN: applied bare, that
rule RAISES any surface trimmed by less than 11.1%, handing back the headroom
the trim just bought. Entries that "hold" are exactly those.

The assertion fails at 98% of budget, not on breach. A surface at its cap
still passed under the old check, which is how nine skills, three agents and
one guide drifted to 98-100% of cap while every suite stayed green.

Adding a new top-level guide: measure len(Path("<name>.md").read_text()),
apply `ratchet(chars, <a first budget>, 10)`, add the entry below.
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
    # Bumped 8090 -> 8300 (story-001) for one clause naming the skill that
    # verifies `stack.worktree_bootstrap`. A deliberate bump, and NOT paid for
    # by trimming, because there was nothing left to trim honestly: the guide
    # measured 7915 = 97.84%, THIRTEEN characters off the band, and the two
    # paragraphs with any bulk left are the System Context reader list (a
    # sync contract a shipped helper's docstring points at) and the Narrowing
    # consent prose. Cutting either to buy room for a pointer would spend
    # something load-bearing on something that is not.
    #
    # 8300 is still well under the formula's 9040 — measured 8035 = 96.8%,
    # leaving ~100 chars. The next clause here trims first.
    "PROCESS_GUIDE": 8300,
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
