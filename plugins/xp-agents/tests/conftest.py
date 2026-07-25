#!/usr/bin/env python3
"""Shared test helpers for all xp-agents test suites.

Conftest is the canonical import surface for tests:
    from conftest import _SMMTestCase, make_event, ...

The implementations live in focused sibling modules to keep this file small:
- `_paths.py` — tree path constants (the leaf of the tests/ import graph)
- `_bases.py` — the SMM + integration base test cases
- `_repo_bases.py` — the temp-git-repo base case + worktree cleanup
- `_event_fixtures.py` — make_event, write_smm_fixture, signal helpers
- `_hook_inputs.py` — canonical hook input dict factories
- `_in_place_helpers.py` — real processes in known liveness states, for the
  in-place marker suites
- `_spawn_guard.py` — blocks any test from launching the real `claude` binary
  (installed on import; not optional — see that module for the incident)

Sprint fixtures stay inline (single consumer set, ~70 lines).

Module-level setup MUST run at conftest load (env strip, sys.path inserts) —
do not move it. The conftest's directory is on sys.path by virtue of pytest /
unittest discovery, which lets us import from sibling `_*.py` modules.
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
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
# - XP_FILE_DOMAIN_DRIFT_TOLERANCE: read by sprint_cli inside
#   _cmd_validate_domain (per-invocation) to set the validate-domain
#   drift threshold. Tests that exercise that knob pass it explicitly
#   via run_cli's extra_env; a stray export from a dev shell would
#   silently flip the default-tolerance assertions in test_sprint_cli.
# - XP_AGENTS_DATA: init.sh's top-preference SMM data root. It exists precisely
#   so a user can export it from their shell, and plugin developers are users,
#   so a leak is likely rather than theoretical: every test that derives an SMM
#   would litter that real root with one project-id dir per ephemeral temp repo
#   (the regression TestPluginDataIsolation guards). Listed here to keep this
#   registry complete, but the PIN below is what contains it: that assignment
#   overwrites any leaked value, so this strip is belt to its braces.
# - XP_SMM_MIGRATE: init.sh's relocation override. `off` suppresses relocation
#   and `force` performs it despite the teammate-liveness gate, so a leaked
#   value would either hide the migration tests' subject or drive it past the
#   very guard those tests exist to pin. The migration suite sets it
#   explicitly per case.
for _leaked_var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
    "XP_TEAMMATE_NAME",
    "XP_FILE_DOMAIN_DRIFT_TOLERANCE",
    "XP_AGENTS_DATA",
    "XP_SMM_MIGRATE",
):
    os.environ.pop(_leaked_var, None)

# Pin XP_AGENTS_DATA to a throwaway dir for the whole test session. With
# SMM_DIR stripped above, any production code that derives its SMM in-process
# (resolve_smm_dir -> _derive_smm_dir -> init.sh, which inherits os.environ)
# would otherwise fall back to a REAL root and litter it with one project-id
# dir per ephemeral test git repo. Redirecting keeps init.sh's per-repo
# derivation semantics but lands everything under temp, cleaned up at
# interpreter exit. Base classes that os.environ.copy() inherit this and then
# override it with their own per-class temp, so this only affects paths that
# don't set XP_AGENTS_DATA themselves.
#
# Pinned on the TOP-preference var, not CLAUDE_PLUGIN_DATA: a pin that anything
# can outrank is not containment, and XP_AGENTS_DATA outranks it by design.
_test_plugin_data = tempfile.mkdtemp(prefix="xp-agents-test-plugin-data-")
os.environ["XP_AGENTS_DATA"] = _test_plugin_data
atexit.register(shutil.rmtree, _test_plugin_data, ignore_errors=True)

# Same redirect, same reason, for the teammate prompt/tee-log namespace. Anything
# that drives a spawn mkdirs `<root>/<project-id>/<sprint-id>/` for real, and the
# project id is derived from a throwaway temp SMM dir — so the suite minted a real
# directory under the real, SHARED /tmp root and nothing removed it (668 stranded
# dirs; ten suites across three base classes still mint one every run).
#
# A redirect, NOT a post-hoc rmtree of the token back out of the shared root: the
# token is derived from whatever SMM dir a test happens to hold, so one leaked
# SMM_DIR turns that sweep into `rm -rf` of a LIVE project's teammate logs. Here
# the writes simply never land in the real root, which is the same containment
# CLAUDE_PLUGIN_DATA gets above and needs no destructive step to hold.
#
# Honors an inherited value so a parent process can aim a child suite at a root it
# can inspect — test_temp_dir_reaping does exactly that to prove spawns really do
# mint namespaces here, rather than passing because nothing was created at all.
_teammate_log_root = os.environ.get("XP_TEAMMATE_LOG_ROOT")
if not _teammate_log_root:
    _teammate_log_root = tempfile.mkdtemp(prefix="xp-agents-test-teammate-logs-")
    atexit.register(shutil.rmtree, _teammate_log_root, ignore_errors=True)
os.environ["XP_TEAMMATE_LOG_ROOT"] = _teammate_log_root


# ---------------------------------------------------------------------------
# Path setup — allow importing production modules. _bases.py owns the
# canonical _PLUGIN_ROOT / _SCRIPTS_DIR / _SMM_DIR; conftest re-exports.
#
# `_spawn_guard` below is imported for its SIDE EFFECT as much as its symbol: it
# installs the suite-wide backstop that makes launching the real `claude` binary
# impossible from any test. A test that drives spawn_teammate.main() expecting it
# to REFUSE before spawning is safe only while the refusal works — in a TDD red
# phase it does not, main() falls through to a real `claude -p`, and that agent
# runs this suite and spawns another. It happened: ~20 billable, recursive,
# orphaned agents. See _spawn_guard.py.
# ---------------------------------------------------------------------------
from _bases import (  # noqa: E402, F401
    _CADENCE_CLI_PY,
    _MARKERS_PY,
    _PLUGIN_ROOT,
    _SCRIPTS_DIR,
    _SMM_DIR,
    _TEAMMATE_CONFIG_CLI_PY,
    _HookTestCase,
    _IntegrationTestCase,
    _SMMTestCase,
    _TempRepoTestCase,
    cleanup_test_worktrees,
)
from _budget_helpers import (  # noqa: E402, F401
    _HISTORICAL_ID_RE,
    _LEAKY_GIT_ENV,
    _PRELOAD_SCRIPT_NAME_OVERRIDES,
    _bootstrap_seeded_smm,
    _md_files,
    _preload_script_name,
    _preload_script_path,
    _run_emitter,
    _run_preload,
    assert_budgets_match,
    assert_emitter_under_budgets,
    assert_md_budgets_match,
    assert_md_under_budgets,
    assert_no_12hex_ids_in_md,
    assert_preload_under_budgets,
    discover_emitter_scripts,
    discover_preload_scripts,
)
from _lint_fixtures import _LintTmpDirMixin, _mock_ruff_result  # noqa: E402, F401
from _md_helpers import (  # noqa: E402, F401
    PROJECT_AGNOSTIC_FORBIDDEN_VOCAB,
    _slice,
    _split_frontmatter_body,
    assert_project_agnostic,
)
from _spawn_guard import RealAgentSpawnBlocked  # noqa: E402, F401
from _stream_stdin_fixtures import _PipeStdinMixin  # noqa: E402, F401
from _test_typing import _MixinBase  # noqa: E402, F401
from _worktree_fixtures import _NormalizePathIdentityMixin  # noqa: E402, F401

sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SMM_DIR))
import _common  # noqa: E402

# Neutralize the ambient process-cwd leak (concern 464de40cd905), mirroring the
# leaky-env strip above. When lefthook runs pytest inside a teammate worktree,
# os.getcwd() returns the worktree path; identity._process_cwd() would leak it
# into is_worktree_teammate and misdetect unrelated tests (which build synthetic
# hook input with no 'cwd') as teammates — failing ~85 hook tests. Pin it to ''
# at conftest load so detection relies only on an explicit input_data['cwd']; the
# two process-cwd fallback tests patch identity._process_cwd to opt back in.
# Module-level (not a pytest fixture) so it fires under both pytest and the
# documented `python3 -m unittest` fallback runner.
import identity  # noqa: E402

identity._process_cwd = lambda: ""

# Module-level re-exports of sibling production modules (smm/ + scripts/)
# so test files can `from conftest import event_schema, sprint_store, ...`
# instead of duplicating the sys.path.insert + bare-import dance.
import event_schema  # noqa: E402, F401
import execution_plan_store  # noqa: E402, F401
import sprint_store  # noqa: E402, F401
import triage  # noqa: E402, F401
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
    adopt_try_event,
    commit_event,
    defer_try_event,
    drop_try_event,
    failing_tests_concern,
    file_write_status,
    make_event,
    make_retrospective_with_try,
    make_session_history_entry,
    passing_tests_status,
    tests_run_status,
    triage_event,
    verify_events,
    write_events,
    write_smm_fixture,
)
from _hook_inputs import (  # noqa: E402, F401
    _make_agent_input,
    _make_bash_failure_input,
    _make_bash_input,
    _make_plan_mode_input,
    _make_skill_input,
    _make_stop_input,
    _make_task_completed_input,
    _make_teammate_idle_input,
    _make_write_input,
)
from _in_place_helpers import (  # noqa: E402, F401
    CHILD_WAIT_TIMEOUT_S,
    Holder,
    dead_in_place_holder,
    dead_pid,
    held_door_mutex,
    live_in_place_holder,
    live_pid,
    reap,
    release_in_place_holds,
)

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (  # noqa: E402, F401
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
)
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

SPRINT_CLOSING_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "closing")]
)

SPRINT_READY_ONLY = _sprint_json([_s("story-001", "As a user I can log in", "ready")])

SPRINT_SCHEDULED_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "scheduled")]
)

# The /xp-story-close window: one story closing, the next frontier still
# scheduled. No story is in-progress, but the schedule gate must stay quiet —
# review-cycle fixes belong to the closing story, not the unpromoted next one.
SPRINT_CLOSING_WITH_NEXT_SCHEDULED = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "closing"),
        _s("story-002", "As a user I can register", "scheduled"),
    ]
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

    def _seed_event(
        self,
        event_type: str,
        content: str,
        files: list[str],
        ts: str | None = None,
        *,
        cycle_id: str | None = None,
        close_mode: str = "sprint",
    ) -> str:
        """Append an event of `event_type`; optional ts overrides make_event's
        default. When `cycle_id` is set, populates `metadata.close_cycle_id`
        + `metadata.close_mode` for in-sprint-batch probe pool tests.
        """
        kwargs: dict = {"content": content, "files": files}
        if ts is not None:
            kwargs["ts"] = ts
        if cycle_id is not None:
            kwargs["metadata"] = {
                "close_cycle_id": cycle_id,
                "close_mode": close_mode,
            }
        e = make_event(event_type, **kwargs)
        _common.append_safe(self.smm_dir, e)
        return e["id"]

    def _seed_concern(
        self,
        content: str,
        files: list[str],
        ts: str | None = None,
        *,
        cycle_id: str | None = None,
        close_mode: str = "sprint",
    ) -> str:
        return self._seed_event(
            EVENT_TYPE_CONCERN,
            content,
            files,
            ts=ts,
            cycle_id=cycle_id,
            close_mode=close_mode,
        )

    def _seed_discovery(
        self,
        content: str,
        files: list[str],
        ts: str | None = None,
        *,
        cycle_id: str | None = None,
        close_mode: str = "sprint",
    ) -> str:
        return self._seed_event(
            EVENT_TYPE_DISCOVERY,
            content,
            files,
            ts=ts,
            cycle_id=cycle_id,
            close_mode=close_mode,
        )

    def _seed_debt(
        self,
        content: str,
        files: list[str],
        ts: str | None = None,
    ) -> str:
        return self._seed_event(EVENT_TYPE_DEBT, content, files, ts=ts)

    def _seed_anchor_in_cycle(
        self,
        cycle_id: str,
        files: list[str] | None = None,
        ts: str | None = None,
    ) -> str:
        """Seed an in-cycle anchor concern: file-overlap with auth.py by
        default (matches the pool tests' canonical anchor shape) plus
        metadata.close_cycle_id to trigger _find_active_cycle_id.
        """
        return self._seed_concern(
            "anchor with cycle",
            files if files is not None else ["scripts/auth.py"],
            ts=ts,
            cycle_id=cycle_id,
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
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Status:** in-progress
- **Dependencies:** story-001

### story-003: Admin user list
- **Status:** ready
- **Dependencies:** story-001
"""
