#!/usr/bin/env python3
"""Shared test helpers for all xp-agents test suites.

Conftest is the canonical import surface for tests:
    from conftest import _SMMTestCase, make_event, ...

The implementations live in focused sibling modules to keep this file small:
- `_bases.py` — base test cases + path constants
- `_event_fixtures.py` — make_event, write_smm_fixture, signal helpers
- `_hook_inputs.py` — canonical hook input dict factories

Sprint fixtures stay inline (single consumer set, ~70 lines).

Module-level setup MUST run at conftest load (env strip, sys.path inserts) —
do not move it. The conftest's directory is on sys.path by virtue of pytest /
unittest discovery, which lets us import from sibling `_*.py` modules.
"""

import json
import os
import sys

# Strip environment variables that would leak a parent shell's state into
# test subprocesses.
# - GIT_*: git sets these during commits/worktrees; inheriting them makes
#   subprocess calls target the parent repo instead of the temp repo.
#   Known issue: pre-commit#3032, lefthook#1265.
# - SMM_DIR: now honored by init.sh / _append_impl.resolve_smm_dir; a stray
#   export from a dev shell would silently redirect every test's SMM writes.
for _leaked_var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
):
    os.environ.pop(_leaked_var, None)

# ---------------------------------------------------------------------------
# Path setup — allow importing production modules. _bases.py owns the
# canonical _PLUGIN_ROOT / _SCRIPTS_DIR / _SMM_DIR; conftest re-exports.
# ---------------------------------------------------------------------------

from _bases import (  # noqa: E402, F401
    _PLUGIN_ROOT,
    _SCRIPTS_DIR,
    _SMM_DIR,
    _HookTestCase,
    _IntegrationTestCase,
    _SMMTestCase,
    _TempRepoTestCase,
    cleanup_test_worktrees,
)

sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SMM_DIR))
from _cli_helpers import (  # noqa: E402, F401
    VALID_MILESTONE,
    VALID_SOURCE,
    make_milestone_dict,
    make_plan_dict,
    run_cli,
)
from _event_fixtures import (  # noqa: E402, F401
    failing_tests_concern,
    make_event,
    passing_tests_status,
    write_smm_fixture,
)
from _hook_inputs import (  # noqa: E402, F401
    _make_agent_input,
    _make_bash_input,
    _make_skill_input,
    _make_stop_input,
    _make_task_completed_input,
    _make_teammate_idle_input,
    _make_write_input,
)

# ---------------------------------------------------------------------------
# Sprint fixtures — kept inline; single consumer set across tests, no need
# for a separate module.
# ---------------------------------------------------------------------------

_STORY_BASE = {
    "milestone_ref": "",
    "design_sources": "",
    "context": "",
    "file_domain": [],
    "interface_contracts": [],
    "acceptance_criteria": [],
}


def _s(id: str, title: str, size: str, status: str, **kw) -> dict:
    deps = kw.pop("dependencies", [])
    return {
        **_STORY_BASE,
        "id": id,
        "title": title,
        "size": size,
        "status": status,
        "dependencies": deps,
        **kw,
    }


def _sprint_json(
    stories,
    sprint_id="",
    started="",
    goal="Build auth",
    milestone="",
):
    return json.dumps(
        {
            "sprint_id": sprint_id,
            "goal": goal,
            "started": started,
            "milestone": milestone,
            "stories": stories,
        }
    )


SPRINT_IN_PROGRESS = _sprint_json(
    [_s("story-001", "As a user I can log in", "M", "in-progress")]
)

SPRINT_READY_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "M", "ready")]
)

SPRINT_ALL_DONE = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "M", "done"),
        _s("story-002", "As a user I can register", "S", "deferred"),
    ]
)

SPRINT_COMPLETE_WITH_ID = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "M", "done"),
        _s("story-002", "As a user I can register", "S", "deferred"),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

SPRINT_MIXED = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "M", "done"),
        _s("story-002", "As a user I can register", "S", "ready"),
        _s(
            "story-003",
            "As an admin I can list users",
            "L",
            "ready",
            dependencies=["story-002"],
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

SPRINT_MIXED_IN_PROGRESS = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "M", "done"),
        _s(
            "story-002",
            "As a user I can register",
            "S",
            "in-progress",
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

# Rendered markdown sprint — used by preload-based tests (test_assign,
# test_subagent_tiers, test_teammate_guide) that write to sprint.json
# in rendered markdown format rather than raw JSON.
SAMPLE_SPRINT_MD = """\
# Sprint: Build user management REST API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: User registration
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001

### story-003: Admin user list
- **Size:** S
- **Status:** ready
- **Dependencies:** story-001
"""
