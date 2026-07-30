#!/usr/bin/env python3
"""Per-emitter character budgets — exercises full script logic.

Each additionalContext-emitting hook script is invoked via subprocess
against an init'd SMM (created per-call by `init.sh`) with a representative
fixture stdin. The stdout character length is asserted against a per-script
budget (decoded UTF-8; for ASCII emitters bytes == chars).

Because the runner bootstraps a real SMM (seed_smm.py), scripts execute
their FULL logic path — not the SMM-missing short-circuit at
`get_validated_smm_dir`. Zero chars today is a legitimate
"no-trigger" result, not a short-circuit.

Today's measurements (seeded-but-empty SMM, git-repo cwd, neutral fixture):
- subagent_start (4096 chars): renders SMM + XP_VALUES.md
- session_start (1793 chars): SessionStart preload framing
- subagent_stop (248 chars): plan-reviewer nudge string
- lint_check (235 chars): missing-linter warning
- review_cycle_done (110 chars): close-reviewer-completion follow-up nudge
- session_end_warning (81 chars): session-end reminder (always emits, even on
  zero unresolved concerns)
- prompt_nugget, retrospective (0 chars): no signals to nugget
- pre_tool_write, pre_tool_bash (0 chars): no sprint state, gate emitters silent
- user_prompt_log (0 chars): returns None by design

Order coupling: amortization runs all 11 emitters against ONE SMM. An
emitter that writes events.jsonl or markers (e.g. subagent_stop's
.assign-pending) could inflate later emitters' output. Today only
subagent_stop has known side effects, and it's ordered last in the
sweep — but a future emitter with side effects must either be ordered
last too or get its own SMM.

What this test catches:
- Growth in any emitter's no-trigger output (e.g. an unconditional prose
  injection added to a previously-silent emitter).
- Growth in the always-on framing on session_start / subagent_start.
- Regression past per-script budgets on the four emitters that emit on
  empty-SMM today (subagent_stop nudge, lint_check warning, review_cycle
  follow-up).

What this test does NOT catch:
- Growth in dynamic per-event content (rendered SMM, file paths, signal
  counts) — those scale with SMM size and are validated by per-script unit
  tests in this directory.

Budgets are `ratchet(measured, current, 100, rounding=ceil, floor=100)`,
and the assertion fails at 98% of budget rather than on breach.

TEN of the fifteen entries below measure 0 chars: the fixture drives the
emitter's no-trigger path, so those budgets bound nothing that is actually
exercised. `ratchet` refuses to lower a zero measurement for exactly that
reason — encoding 0 as the bound would record the fixture gap as the rule.
Fixing those fixtures is separate work; until then, read those ten entries as
placeholders, not as coverage.

Adding a new emitter: add a fixture builder in `_emitter_fixtures.py`,
run `assert_emitter_under_budgets` once to measure stdout chars, then
`ratchet(measured, <a first budget>, 100, rounding=math.ceil, floor=100)`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _emitter_fixtures import EMITTER_BUDGETS, EMITTER_FIXTURES
from conftest import (
    _SCRIPTS_DIR,
    assert_budgets_match,
    assert_emitter_under_budgets,
    discover_emitter_scripts,
)

_LABEL = "scripts/*.py emitter"


class TestInjectionBudgets(unittest.TestCase):
    def test_every_emitter_has_budget_entry(self):
        assert_budgets_match(self, EMITTER_FIXTURES, EMITTER_BUDGETS, _LABEL)

    def test_no_emitter_exceeds_its_budget(self):
        assert_emitter_under_budgets(self, _SCRIPTS_DIR, EMITTER_BUDGETS, _LABEL)

    def test_every_emitter_in_scripts_dir_has_budget_entry(self):
        """Surface-scan: walk scripts/ for hook_output emitters; fail loud on any
        that ship without a budget entry. Closes c589e66f9a22 (AC1 enforcement
        gap) — the symmetric fixture↔budget check passes vacuously when an
        emitter has neither, this catches it."""
        on_disk = set(discover_emitter_scripts(_SCRIPTS_DIR))
        missing = on_disk - set(EMITTER_BUDGETS)
        self.assertFalse(
            missing,
            f"{_LABEL} scripts on disk without a budget entry: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
