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


# The liveness refusal's own heading, as `skills/_preload_liveness.sh` echoes
# it. It must not be confusable with the base's pre-existing no-SMM-at-all exit:
# "there is no shared model here" and "the shared model is here but the runtime
# maintaining it is dead" are different failures with different fixes.
#
# Anchored in this shared module rather than in whichever suite spelled it
# first: two suites now assert against it, and importing a `test_*` module for a
# constant makes pytest execute that file under a second module name. No
# separate pin against the shell fragment is needed — every consumer asserts it
# against REAL preload stdout, so a reworded banner goes red there.
REFUSAL_HEADER = "## Hook Runtime: not live"


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
#
# Lives here, beside the fixtures, rather than in the suite that asserts it:
# `tests/test_volume_budgets.py` needs these numbers as the floor its own
# measurements must clear, and importing a `test_*` module for a constant makes
# pytest execute that file under a second module name.
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
    # First budget for the finished surface, from the formula: measured 108, so
    # ceil(108 * 1.125 / 100) * 100 = 200. The registration increment's 100 was
    # the floor applied to a 28-char skeleton, which is not this surface — the
    # ratchet cannot raise, so the number is re-derived rather than nudged.
    "xp-scaffold-worktree": 200,
    "xp-schedule": 200,
    "xp-sprint-close": 8900,
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
