#!/usr/bin/env python3
"""Per-preload env-var builders for `tests/hooks/test_preload_budgets.py`.

Each builder returns the env-var dict needed to drive a preload's
representative branch via subprocess. Preloads are .sh scripts that
read env vars set by the orchestrator (TEAMMATE_CWD, CLOSE_START_TS,
etc.), so builders return env additions; SMM_DIR + CLAUDE_PLUGIN_ROOT
are injected by `_run_preload`.

Story-001 ships an empty registry (vacuous pass). Wave-2 trim stories
(002-005, 007) APPEND their entries as they trim and measure each
preload's stdout bytes.

Resolves preload skill name to script path:
- xp-kickoff key → skills/xp-kickoff/scripts/check_session_needs.sh
- all other keys → skills/<name>/scripts/preload.sh
"""

from collections.abc import Callable

PreloadBuilder = Callable[[], dict]


def _empty() -> dict:
    """Builder for preloads that exercise the no-state early-exit branch.

    Bootstrap SMM has no sprint.json / system_context.json / .plan-awaiting-review
    marker, so these preloads route to their no-state branch with no extra env.
    """
    return {}


PRELOAD_FIXTURES: dict[str, PreloadBuilder] = {
    "xp-accept": _empty,
    "xp-quality-review": _empty,
    "xp-review-plan": _empty,
    "xp-system-context": _empty,
}
