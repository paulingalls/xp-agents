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


def _no_env() -> dict:
    """Preload reads only base env (SMM_DIR, CLAUDE_PLUGIN_ROOT, XP_TEAMMATE_NAME)."""
    return {}


PRELOAD_FIXTURES: dict[str, PreloadBuilder] = {
    "xp-kickoff": _no_env,
    "xp-work-selection": _no_env,
    "xp-end-session": _no_env,
}
