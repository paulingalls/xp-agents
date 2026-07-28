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
    "xp-schedule": _no_env,
    "xp-sprint-close": _no_env,
    "xp-sprint-review": _no_env,
    "xp-sprint-start": _no_env,
    "xp-story-close": _no_env,
    "xp-system-context": _no_env,
    "xp-work-selection": _no_env,
}
