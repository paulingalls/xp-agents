#!/usr/bin/env python3
"""Per-emitter byte budgets — empty-SMM baseline regression guard.

Each additionalContext-emitting hook script is executed via subprocess
against an isolated empty SMM with a representative fixture stdin. The
stdout byte length is asserted against a per-script budget.

Today's baseline: only `session_start.py` and `subagent_start.py` emit
non-zero output on empty SMM (they ship XP_VALUES.md framing
unconditionally); the other nine return 0 bytes. The 100-byte budget on
those nine is a "stays near zero" guard — it catches a refactor that
accidentally introduces unconditional prose.

What this test catches:
- Growth in the always-emit framing on session_start / subagent_start.
- New unconditional output sneaking into a previously-silent emitter.

What this test does NOT catch:
- Growth in dynamic per-event content (rendered SMM, file paths, signal
  counts) — those scale with SMM size and are validated by the per-script
  unit tests in this directory.

Adding a new emitter: add a fixture builder in `_emitter_fixtures.py`,
run `assert_emitter_under_budgets` once to measure stdout bytes, compute
``round(measured * 1.125 / 100) * 100`` (floor at 100), add an entry below.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    _SCRIPTS_DIR,
    assert_emitter_budgets_match,
    assert_emitter_under_budgets,
)

# round(measured_bytes * 1.125 / 100) * 100, floor at 100.
EMITTER_BUDGETS: dict[str, int] = {
    "prompt_nugget.py": 100,
    "user_prompt_log.py": 100,
    "session_start.py": 2000,
    "subagent_start.py": 1900,
    "subagent_stop.py": 100,
    "pre_tool_write.py": 100,
    "pre_tool_bash.py": 100,
    "lint_check.py": 100,
    "review_cycle_done.py": 100,
    "retrospective.py": 100,
    "session_end_warning.py": 100,
}

_LABEL = "scripts/*.py emitter"


class TestInjectionBudgets(unittest.TestCase):
    def test_every_emitter_has_budget_entry(self):
        assert_emitter_budgets_match(self, EMITTER_BUDGETS, _LABEL)

    def test_no_emitter_exceeds_its_budget(self):
        assert_emitter_under_budgets(self, _SCRIPTS_DIR, EMITTER_BUDGETS, _LABEL)


if __name__ == "__main__":
    unittest.main()
