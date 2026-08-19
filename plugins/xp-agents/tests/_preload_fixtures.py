#!/usr/bin/env python3
"""Per-preload env-var builders for `tests/hooks/test_preload_budgets.py`.

Each builder returns the env-var dict needed to drive a preload's
representative branch via subprocess. Preloads are .sh scripts that
read env vars set by the orchestrator (TEAMMATE_CWD, CLOSE_START_TS,
etc.), so builders return env additions; SMM_DIR + CLAUDE_PLUGIN_ROOT
are injected by `_run_preload`.

Wave-2 trim stories (002-005, 007) APPEND entries as they trim and
measure each preload's stdout bytes against the registered budget.

Resolves preload skill name to script path:
- xp-kickoff key → skills/xp-kickoff/scripts/check_session_needs.sh
- all other keys → skills/<name>/scripts/preload.sh
"""

from collections.abc import Callable

PreloadBuilder = Callable[[], dict]


def _no_env() -> dict:
    """Preload reads only base env (SMM_DIR, CLAUDE_PLUGIN_ROOT, XP_TEAMMATE_NAME).

    Bootstrap SMM has no sprint.json / system_context.json / .plan-awaiting-review
    marker, so these preloads route to their no-state branch with no extra env.
    """
    return {}


# Non-vacuity: a glob that silently stops matching must fail loudly rather
# than report a green scan of nothing (the story-001 lesson). Duplicated
# across test_preload_wiring.py and test_skill_preload_map.py used to be two
# copies of this same number (concern f81a974e98e8) — homed here because
# importing a `test_*` module for a constant makes pytest execute that file
# under a second module name.
_EXPECTED_PRELOADS = 17


# REFUSAL_HEADER retired with the liveness reader it named. No preload can
# emit that banner any more — the fragment that echoed it is deleted — so a
# constant for it would be a string nothing can produce, and the tripwire that
# watched for it was watching a state that can no longer occur.


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
# free/plan/sprint held at 8,900 for a long time, measured 8,655/8,641/8,660 and
# 60-80 chars clear of the band — the tightest headroom in this family. Step 4b's
# rewrite for the owned broad-review launcher spent that and more, which is what
# the 10,700 bump below pays for: 9,968/9,909/9,928 today, 93%.
#
# BOTH OF THESE ASSERTIONS ARE INEQUALITIES, so a stale number here goes
# unnoticed — this comment claimed the 8,900 hold three lines above the 10,700
# entries that had replaced it. Re-measure when you touch either reference file;
# nothing will tell you.
#
# Lives here, beside the fixtures, rather than in the suite that asserts it:
# `tests/test_volume_budgets.py` needs these numbers as the floor its own
# measurements must clear, and importing a `test_*` module for a constant makes
# pytest execute that file under a second module name.
PRELOAD_BUDGETS: dict[str, int] = {
    "xp-accept": 100,
    "xp-assign": 300,
    "xp-end-session": 200,
    # 8900 -> 10700, and this one is expected to come back DOWN. Close Step 4b
    # now carries two launchers where it carried one: the shipped Workflow
    # script, plus the built-in Skill kept as a documented fallback until the
    # script has closed a real branch. The second launcher's paragraph — its
    # disarm, its differing arm, its prose findings — is the whole increase.
    # `ratchet` only ever lowers, so retiring the fallback re-derives this
    # rather than leaving the room spendable.
    "xp-free-close": 10700,
    "xp-kickoff": 200,
    "xp-plan": 100,
    "xp-plan-close": 10700,  # same shared reference; see xp-free-close above
    "xp-quality-review": 300,
    "xp-review-plan": 100,
    # First budget for the finished surface, from the formula: measured 108, so
    # ceil(108 * 1.125 / 100) * 100 = 200. The registration increment's 100 was
    # the floor applied to a 28-char skeleton, which is not this surface — the
    # ratchet cannot raise, so the number is re-derived rather than nudged.
    "xp-scaffold-worktree": 200,
    "xp-schedule": 200,
    "xp-sprint-close": 10700,  # same shared reference
    "xp-sprint-review": 100,
    "xp-sprint-start": 100,
    "xp-story-close": 6400,
    "xp-system-context": 100,
    "xp-work-selection": 100,
}


PRELOAD_FIXTURES: dict[str, PreloadBuilder] = {
    "xp-accept": _no_env,
    "xp-assign": _no_env,
    "xp-end-session": _no_env,
    "xp-free-close": _no_env,
    "xp-kickoff": _no_env,
    "xp-plan": _no_env,
    "xp-plan-close": _no_env,
    "xp-quality-review": _no_env,
    "xp-review-plan": _no_env,
    "xp-scaffold-worktree": _no_env,
    "xp-schedule": _no_env,
    "xp-sprint-close": _no_env,
    "xp-sprint-review": _no_env,
    "xp-sprint-start": _no_env,
    "xp-story-close": _no_env,
    "xp-system-context": _no_env,
    "xp-work-selection": _no_env,
}
