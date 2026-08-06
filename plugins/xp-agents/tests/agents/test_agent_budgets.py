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
    # Bumped 21940 -> 22800 (story-001, bun spec paths): §10b gained a
    # `bun test <spec>` positional-runner entry, narrowed the whole-tree
    # entry to bun's own alias forms (`bun run <script>`, `bun
    # <script>:<suffix>`), and a sentence on bun positionals being filter
    # patterns rather than strict paths. Deliberate, not a ratchet: without
    # this the reviewer keeps reading every `bun test <spec>` acceptance
    # command as a whole-tree runner and never raises the §10b/10d
    # non-verifiable-command or missing-plan-path concerns for it — the
    # exact gap scripts/verify_paths.py's bun branch closes in code. Not
    # paid for by trimming: the pinned §10b prose
    # (tests/agents/test_plan_reviewer_prose.py) forbids it. Measured 21756
    # after the edit — over the old 98% band (21501), under the new one
    # (22344), which is what makes the bump necessary rather than optional.
    # 21756 is CHARACTERS, which is what this budget counts
    # (assert_md_under_budgets reads len(read_text)). `wc -c` says 21913:
    # that is bytes, and this file is full of multi-byte em dashes, § and
    # arrows. Re-measure with len(), never wc -c, or the ~150-char gap
    # reads as drift that is not there.
    "xp-plan-reviewer": 22800,
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
    #
    # Bumped 20700 -> 21600 (story-018): the surface block gained the
    # independence precondition and the two consent sentences. Deliberate, and
    # deliberately NOT paid for by compressing: this prose is the ONLY place a
    # customer is told what declaring `paths` costs them — that coverage is
    # checked by path and not blast radius, so a break in an unselected surface
    # merges at story close and is caught only at sprint close (93c3a7f51618),
    # and that `stack.test_command` must cover every surface because collapse
    # falls back to it (7011f2040970). Neither risk can be removed in code;
    # consent is the whole answer, so shrinking the sentence that obtains it
    # would ship the story's own defect. Trimmed first: 21120 -> 21056.
    #
    # Bumped 21600 -> 22800 (story-001): Step 3.75 now says that a command it
    # recorded is UNVERIFIED and names the skill that can verify it. The rule
    # against inventing a command was vindicated by measurement and is
    # untouched; what was missing is that a DOCUMENTED command is not a
    # MEASURED one — two plausible candidates both exited 0 and one closed
    # nothing, so a recorded value that reads as verified is precisely the
    # false green the measurement exists to kill.
    #
    # Trimmed first, but only by 62 chars (an illustrative parenthetical), and
    # the bump is larger than the net addition of 242 on purpose. The entry
    # arrived at 97.99% — two characters off the band — because each of the
    # three bumps before this one bought back barely more than it spent, which
    # is the drift this module's docstring names. 22800 leaves ~1400 chars, so
    # the next true clarification here is an edit rather than a fourth bump.
    "xp-system-analyzer": 22800,
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
