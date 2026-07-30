#!/usr/bin/env python3
"""Per-preload character budgets — exercises full preload.sh logic.

Each preload.sh script (and xp-kickoff's check_session_needs.sh, the
preload-equivalent named differently) is invoked via subprocess against
an init'd SMM (created per-call by `init.sh`) with a representative
fixture env. The stdout character length is asserted against a per-script
budget (decoded UTF-8; for ASCII preloads bytes == chars).

Because the runner bootstraps a real SMM (seed_smm.py) inside a git repo,
preloads execute their FULL logic path — including helpers they invoke
(session_history_cli.py, triage_preload.py, debt_for_files.py, etc.)
whose stdout flows into the preload's additionalContext.

The assertion fails at 98% of budget, not on breach — a preload that has
crept to its cap is reported while it can still be trimmed cheaply, which is
the difference between a warning and an outage.

Adding a new preload: add a fixture builder in `_preload_fixtures.py`,
run `assert_preload_under_budgets` once to measure stdout chars, then
`ratchet(measured, <a first budget>, 100, rounding=math.ceil, floor=100)`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _preload_fixtures import PRELOAD_FIXTURES
from conftest import (
    assert_budgets_match,
    assert_preload_under_budgets,
    discover_preload_scripts,
)

# ratchet(measured, current, 100, rounding=ceil, floor=100) — see
# `_budget_helpers.ratchet`. Recalculated from post-audit sizes; a budget may
# only ever come DOWN, so an entry whose measured size fell by less than 11.1%
# keeps the number it already had.
#
# The close preloads dominate this family: each appends a shared reference
# file, so a char added there costs once per mode that appends it. Steps 4 and
# 4b now live in a second file appended only by free/plan/sprint, which is what
# took story-close from 8,730 (98.09% of 8,900 — inside the band, and
# unfixable by any budget change, since the ratchet computes higher and a
# ratchet may not raise) down to 5,668 and a budget of 6,400.
#
# free/plan/sprint measured 8,655/8,641/8,660 and HOLD at 8,900: the ratchet
# wants 9,800 for them, so the monotonic guard pins them where they are. They
# sit at 97.1-97.3%, roughly 60-80 chars clear of the 98% band. That is the
# tightest headroom in this family by a wide margin — the next edit to either
# reference file is what those chars are for, and there is no slack for prose
# that could live in one mode's SKILL.md instead.
PRELOAD_BUDGETS: dict[str, int] = {
    "xp-accept": 100,
    "xp-assign": 300,
    "xp-end-session": 200,
    "xp-free-close": 8900,
    "xp-kickoff": 200,
    "xp-plan": 100,
    "xp-plan-close": 8900,
    "xp-quality-review": 300,
    "xp-review-plan": 100,
    "xp-schedule": 200,
    "xp-sprint-close": 8900,
    "xp-sprint-review": 100,
    "xp-sprint-start": 100,
    "xp-story-close": 6400,
    "xp-system-context": 100,
    "xp-work-selection": 100,
}

_LABEL = "skills/*/scripts/preload.sh"


class TestPreloadBudgets(unittest.TestCase):
    def test_every_preload_has_budget_entry(self):
        assert_budgets_match(self, PRELOAD_FIXTURES, PRELOAD_BUDGETS, _LABEL)

    def test_no_preload_exceeds_its_budget(self):
        assert_preload_under_budgets(self, PRELOAD_BUDGETS, _LABEL)

    def test_worktree_path_segment_does_not_inflate_budget(self):
        """Location-independence (concern 464de40cd905): when lefthook runs the
        suite from a teammate worktree, echoed absolute paths (CLAUDE_PLUGIN_ROOT)
        carry an extra '/.claude/worktrees/worktree-<id>' segment. Budget
        measurement must strip it so a worktree run measures the same as the main
        checkout — otherwise every teammate's pre-commit budget check fails."""
        from _budget_helpers import _measured_len

        main = b"PLUGIN_ROOT=/repo/plugins/xp-agents\n"
        worktree = (
            b"PLUGIN_ROOT=/repo/.claude/worktrees/worktree-story-1/plugins/xp-agents\n"
        )
        self.assertEqual(_measured_len(main), _measured_len(worktree))

    def test_checkout_path_length_does_not_inflate_budget(self):
        """Location-independence (concern b2e542c120b9): a preload echoes
        PLUGIN_ROOT/SMM_DIR/cwd as absolute paths, so the measured stdout
        length includes the checkout path length itself, not just the
        worktree segment. Passing normalize_paths must make a short and a
        deep checkout path measure identically."""
        from _budget_helpers import _measured_len

        short_root = "/p"
        long_root = (
            "/Users/someone/src/projects/xp-agents/.claude/worktrees/"
            "worktree-story-013-preload-budget-checkout-independent"
        )
        short_stdout = (
            f"PLUGIN_ROOT={short_root}\nscripts dir: {short_root}/scripts\n".encode()
        )
        long_stdout = (
            f"PLUGIN_ROOT={long_root}\nscripts dir: {long_root}/scripts\n".encode()
        )
        self.assertEqual(
            _measured_len(short_stdout, normalize_paths=(short_root,)),
            _measured_len(long_stdout, normalize_paths=(long_root,)),
        )

    def test_content_overflow_still_fails_with_normalization(self):
        """AC2: normalization must not disarm the budget check — genuine
        content overflow (not path length) still trips it."""
        from _budget_helpers import _measured_len

        root = "/p"
        short = f"PLUGIN_ROOT={root}\n".encode()
        bloated = f"PLUGIN_ROOT={root}\n" + ("x" * 500) + "\n"
        bloated_bytes = bloated.encode()
        self.assertLess(
            _measured_len(short, normalize_paths=(root,)),
            _measured_len(bloated_bytes, normalize_paths=(root,)),
        )

    def test_every_preload_in_skills_dir_has_budget_entry(self):
        """Surface-scan: walk skills/*/scripts/ for preload-emitter scripts; fail
        loud on any without a budget entry. Mirror of story-008's emitter-side
        scan — closes the new-preload-ships-unbudgeted gap that the symmetric
        fixture↔budget check passes vacuously."""
        on_disk = set(discover_preload_scripts())
        missing = on_disk - set(PRELOAD_BUDGETS)
        self.assertFalse(
            missing,
            f"{_LABEL} skills on disk without a budget entry: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
