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

Adding a new emitter: add a fixture builder in `_emitter_fixtures.py`,
run `assert_emitter_under_budgets` once to measure stdout chars, compute
``ceil(measured * 1.125 / 100) * 100`` (floor at 100), add an entry below.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _emitter_fixtures import EMITTER_FIXTURES
from conftest import (
    _SCRIPTS_DIR,
    assert_budgets_match,
    assert_emitter_under_budgets,
    discover_emitter_scripts,
)

# ceil(measured_chars * 1.125 / 100) * 100, floor at 100.
EMITTER_BUDGETS: dict[str, int] = {
    "bash_post_tool.py": 100,
    "kickoff_gate.py": 100,
    "lint_check.py": 300,
    "post_tool_exit_plan.py": 100,
    "pre_tool_bash.py": 100,
    "pre_tool_skill.py": 100,
    "pre_tool_write.py": 100,
    "prompt_nugget.py": 100,
    "retrospective.py": 100,
    "review_cycle_done.py": 200,
    "session_end_warning.py": 100,
    "session_start.py": 2100,
    "subagent_start.py": 4700,
    "subagent_stop.py": 300,
    "user_prompt_log.py": 100,
}

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
