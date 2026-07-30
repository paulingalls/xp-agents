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

Story-001 ships an empty PRELOAD_BUDGETS + empty PRELOAD_FIXTURES so both
tests pass vacuously. Wave-2 trim stories (002-005, 007) APPEND entries
as they trim and measure each preload.

Adding a new preload: add a fixture builder in `_preload_fixtures.py`,
run `assert_preload_under_budgets` once to measure stdout chars, compute
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
    discover_preload_scripts,
)

# ceil(measured_chars * 1.125 / 100) * 100, floor at 100.
#
# The four close preloads are the exception: each `cat`s the shared
# close-pipeline reference, so a char added there costs 4x and the wave-2 trim
# stories set these to the next hundred above measured rather than the 1.125
# headroom, deliberately keeping the trim pressure on. Bumped 7800/7900 -> 8300
# when the shared Step 6 abort-default gained the close-diff pipe
# (`count-concerns --diff-paths -`), so an unrelated open concern filed in the
# same window can no longer abort a clean close. The added paragraph was
# re-trimmed to five lines first; the per-mode SKILLs carry a one-liner each.
# Measured at that bump: free 8237, plan 8223, sprint 8242, story 8295.
# Bumped 8300 -> 8400 when the shared Step 5c worktree-commit note gained the
# literal-path rule: the hard `-C` refusal shipped in v5.1.0 was taught in one
# of four places, and not the one a teammate reads, so a lead following this
# block hit a refusal the block never mentioned. One line, four preloads.
# Measured at that bump: free 8303, plan 8289, sprint 8308, story 8361.
# Bumped 8400 -> 8900 for shared Step 6b, which releases the close-cycle id
# marker. Not prose that could live in one mode's SKILL.md: the marker is what
# tags concerns with the close they were raised during, and an id left behind
# tags concerns raised AFTER its close ended — which the next close's
# `--cycle-id` count then excludes, dropping a concern the gate should have
# counted. Every mode gates on that count, so every mode needs the release.
# Written at four lines plus the command (a first draft at ~1100 chars was cut
# to ~440 before this bump was taken).
# Measured at that bump: free 8746, plan 8732, sprint 8751, story 8804.
# NOT bumped for story-003's `--no-renames ... -z` capture flags (+16 chars per
# site, x4 preloads): the flags fit, the sentence explaining WHY they are there
# did not, and it was dropped rather than take a fifth bump for prose. Read the
# headroom before writing here — measured after: free 8834, plan 8820, sprint
# 8839, story 8892. Story-close now has EIGHT characters. The next edit to
# `_close_pipeline_shared.md` that is longer than that needs a bump, not a trim.
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
    "xp-story-close": 8900,
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
