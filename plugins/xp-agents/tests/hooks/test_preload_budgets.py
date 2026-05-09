#!/usr/bin/env python3
"""Per-preload byte budgets — exercises full preload.sh logic.

Each preload.sh script (and xp-kickoff's check_session_needs.sh, the
preload-equivalent named differently) is invoked via subprocess against
an init'd SMM (created per-call by `init.sh`) with a representative
fixture env. The stdout byte length is asserted against a per-script budget.

Because the runner bootstraps a real SMM (seed_smm.py) inside a git repo,
preloads execute their FULL logic path — including helpers they invoke
(render_history.py, triage_preload.py, debt_for_files.py, etc.) whose
stdout flows into the preload's additionalContext.

Story-001 ships an empty PRELOAD_BUDGETS + empty PRELOAD_FIXTURES so both
tests pass vacuously. Wave-2 trim stories (002-005, 007) APPEND entries
as they trim and measure each preload.

Adding a new preload: add a fixture builder in `_preload_fixtures.py`,
run `assert_preload_under_budgets` once to measure stdout bytes, compute
``ceil(measured * 1.125 / 100) * 100`` (floor at 100), add an entry below.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _preload_fixtures import PRELOAD_FIXTURES
from conftest import (
    assert_budgets_match,
    assert_preload_under_budgets,
)

# ceil(measured_bytes * 1.125 / 100) * 100, floor at 100.
PRELOAD_BUDGETS: dict[str, int] = {}

_LABEL = "skills/*/scripts/preload.sh"


class TestPreloadBudgets(unittest.TestCase):
    def test_every_preload_has_budget_entry(self):
        assert_budgets_match(self, PRELOAD_FIXTURES, PRELOAD_BUDGETS, _LABEL)

    def test_no_preload_exceeds_its_budget(self):
        assert_preload_under_budgets(self, PRELOAD_BUDGETS, _LABEL)


if __name__ == "__main__":
    unittest.main()
