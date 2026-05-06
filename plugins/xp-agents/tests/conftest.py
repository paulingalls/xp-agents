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
from pathlib import Path

# Strip environment variables that would leak a parent shell's state into
# test subprocesses.
# - GIT_*: git sets these during commits/worktrees; inheriting them makes
#   subprocess calls target the parent repo instead of the temp repo.
#   Known issue: pre-commit#3032, lefthook#1265.
# - SMM_DIR: now honored by init.sh / _append_impl.resolve_smm_dir; a stray
#   export from a dev shell would silently redirect every test's SMM writes.
# - XP_TEAMMATE_NAME: set by the CLI teammate launcher and read by both
#   identity.is_worktree_teammate (as a fallback when cwd lacks a worktree
#   marker) and the SessionStart hook (to choose the teammate guide). When
#   it leaks from a teammate shell into test subprocesses, ~50 hook /
#   integration tests get True on "non-teammate" paths or assert against
#   the wrong guide, breaking every teammate's pre-commit downstream.
for _leaked_var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
    "XP_TEAMMATE_NAME",
):
    os.environ.pop(_leaked_var, None)

# ---------------------------------------------------------------------------
# Path setup — allow importing production modules. _bases.py owns the
# canonical _PLUGIN_ROOT / _SCRIPTS_DIR / _SMM_DIR; conftest re-exports.
# ---------------------------------------------------------------------------

from _bases import (  # noqa: E402, F401
    _MARKERS_PY,
    _PLUGIN_ROOT,
    _SCRIPTS_DIR,
    _SMM_DIR,
    _HookTestCase,
    _IntegrationTestCase,
    _SMMTestCase,
    _TempRepoTestCase,
    cleanup_test_worktrees,
)
from _lint_fixtures import _LintTmpDirMixin, _mock_ruff_result  # noqa: E402, F401
from _md_helpers import _split_frontmatter_body  # noqa: E402, F401
from _test_typing import _MixinBase  # noqa: E402, F401

sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SMM_DIR))
import _common  # noqa: E402

# Module-level re-exports of sibling production modules (smm/ + scripts/)
# so test files can `from conftest import event_schema, sprint_store, ...`
# instead of duplicating the sys.path.insert + bare-import dance.
import event_schema  # noqa: E402, F401
import execution_plan_store  # noqa: E402, F401
import sprint_store  # noqa: E402, F401
from _cli_helpers import (  # noqa: E402, F401
    VALID_MILESTONE,
    VALID_SOURCE,
    VALID_SPRINT_STORY,
    make_milestone_dict,
    make_plan_dict,
    make_sprint_dict,
    make_story_dict,
    run_cli,
)
from _event_fixtures import (  # noqa: E402, F401
    commit_event,
    failing_tests_concern,
    file_write_status,
    make_event,
    make_retrospective_with_try,
    passing_tests_status,
    tests_run_status,
    write_events,
    write_smm_fixture,
)
from _hook_inputs import (  # noqa: E402, F401
    _make_agent_input,
    _make_bash_failure_input,
    _make_bash_input,
    _make_skill_input,
    _make_stop_input,
    _make_task_completed_input,
    _make_teammate_idle_input,
    _make_write_input,
)

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS  # noqa: E402
from resolution import compute_resolutions  # noqa: E402, F401

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


def _extract_preload_var(stdout: str, name: str) -> str | None:
    """Extract a VAR=value from preload stdout. Returns value or None.

    Shared by integration tests that drive a preload.sh subprocess and
    parse its KEY=value output (xp-assign, xp-sprint-close, future
    close skills).
    """
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    return None


def _s(id: str, title: str, status: str, **kw) -> dict:
    deps = kw.pop("dependencies", [])
    return {
        **_STORY_BASE,
        "id": id,
        "title": title,
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
    [_s("story-001", "As a user I can log in", "in-progress")]
)

SPRINT_REVIEWING_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "reviewing")]
)

SPRINT_READY_ONLY = _sprint_json([_s("story-001", "As a user I can log in", "ready")])

SPRINT_SCHEDULED_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "scheduled")]
)

SPRINT_ALL_DONE = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "done"),
        _s("story-002", "As a user I can register", "deferred"),
    ]
)

SPRINT_COMPLETE_WITH_ID = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "done"),
        _s("story-002", "As a user I can register", "deferred"),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

SPRINT_MIXED = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "done"),
        _s("story-002", "As a user I can register", "ready"),
        _s(
            "story-003",
            "As an admin I can list users",
            "ready",
            dependencies=["story-002"],
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

SPRINT_MIXED_IN_PROGRESS = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "done"),
        _s(
            "story-002",
            "As a user I can register",
            "in-progress",
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)


class _ProbeTestHelpers:
    """Shared helpers for tests that seed concerns and read probe events."""

    smm_dir: Path

    def _seed_auth_concern(self, content: str = "Auth middleware leaks tokens") -> str:
        c = make_event(EVENT_TYPE_CONCERN, content=content, files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, c)
        return c["id"]

    def _probes(self) -> list[dict]:
        return [
            e
            for e in _common.read_events_raw(self.smm_dir)
            if e.get("type") == EVENT_TYPE_STATUS
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]


# Rendered markdown sprint — used by preload-based tests (test_assign,
# test_subagent_tiers, test_teammate_guide) that write to sprint.json
# in rendered markdown format rather than raw JSON.
SAMPLE_SPRINT_MD = """\
# Sprint: Build user management REST API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: User registration
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Status:** in-progress
- **Dependencies:** story-001

### story-003: Admin user list
- **Status:** ready
- **Dependencies:** story-001
"""
