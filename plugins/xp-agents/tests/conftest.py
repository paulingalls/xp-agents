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
import re
import sys
import unittest
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
for _leaked_var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
    "XP_TEAMMATE_NAME",
    "XP_FILE_DOMAIN_DRIFT_TOLERANCE",
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
from _worktree_fixtures import _NormalizePathIdentityMixin  # noqa: E402, F401

sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SMM_DIR))
import _common  # noqa: E402

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
from _emitter_fixtures import EMITTER_FIXTURES  # noqa: E402
from _event_fixtures import (  # noqa: E402, F401
    commit_event,
    failing_tests_concern,
    file_write_status,
    make_event,
    make_retrospective_with_try,
    make_session_history_entry,
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
from _preload_fixtures import PRELOAD_FIXTURES  # noqa: E402

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

SPRINT_CLOSING_ONLY = _sprint_json(
    [_s("story-001", "As a user I can log in", "closing")]
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


_HISTORICAL_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")


def _md_files(dir_path: Path, pattern: str) -> dict[str, Path]:
    """Map {stem-or-parent-name: path} for shipped *.md files matching pattern.

    Two glob shapes used in this repo:
    - "*/SKILL.md" → key by parent dir name (skill name)
    - "*.md" → key by file stem
    """
    if pattern.endswith("/SKILL.md"):
        return {p.parent.name: p for p in dir_path.glob(pattern)}
    return {p.stem: p for p in dir_path.glob(pattern)}


def assert_md_budgets_match(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every shipped .md must have a budget entry; every entry must match a .md."""
    on_disk = set(_md_files(dir_path, pattern))
    missing = on_disk - set(budgets)
    extra = set(budgets) - on_disk
    testcase.assertFalse(
        missing,
        f"{label} files without a budget entry: {sorted(missing)}",
    )
    testcase.assertFalse(
        extra,
        f"budget entries with no matching {label}: {sorted(extra)}",
    )


def assert_md_under_budgets(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every shipped .md must be at or below its budget."""
    files = _md_files(dir_path, pattern)
    offenders: list[str] = []
    for name, budget in budgets.items():
        actual = len(files[name].read_text(encoding="utf-8").splitlines())
        if actual > budget:
            offenders.append(f"{name}: {actual} lines (budget {budget})")
    testcase.assertFalse(
        offenders,
        f"{label} files exceed their line budget:\n" + "\n".join(offenders),
    )


_LEAKY_GIT_ENV = (
    "SMM_DIR",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
)


def _bootstrap_seeded_smm(tmp: Path) -> tuple[Path, Path]:
    """Create + seed an empty SMM with a git repo cwd. Returns (repo, smm).

    Production-like: scripts run from a git repo (many call `git rev-parse`
    or read repo state), against a seeded SMM. Bypasses init.sh because we
    own SMM_DIR — call seed_smm.py directly to write
    shared_mental_model.json.
    """
    import subprocess

    repo = tmp / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, capture_output=True, check=True)
    smm = tmp / "smm"
    (smm / "retrospectives").mkdir(parents=True)
    (smm / "events.jsonl").touch()
    (smm / "events.lock").touch()
    subprocess.run(
        ["python3", str(_PLUGIN_ROOT / "smm" / "seed_smm.py"), str(smm)],
        check=True,
        capture_output=True,
    )
    return repo, smm


def _run_emitter(
    script_name: str,
    scripts_dir: Path,
    smm_dir: Path,
    cwd: Path,
) -> tuple[bytes, str, int]:
    """Run an emitter via subprocess against a pre-seeded SMM.

    Caller owns smm_dir + cwd lifecycle so multiple emitter invocations
    can share one bootstrap (the budget test runs all 11 against the
    same empty SMM). XP_TEAMMATE_NAME="" forces solo-mode framing —
    `pop` would let a parent shell's leak through.
    """
    import subprocess

    builder = EMITTER_FIXTURES.get(script_name)
    if builder is None:
        raise KeyError(f"no fixture builder registered for {script_name}")
    stdin_dict = builder()

    env = os.environ.copy()
    env["SMM_DIR"] = str(smm_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    env["XP_TEAMMATE_NAME"] = ""
    for ev in _LEAKY_GIT_ENV:
        env.pop(ev, None)
    proc = subprocess.run(
        ["python3", str(scripts_dir / script_name)],
        input=json.dumps(stdin_dict).encode("utf-8"),
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=15,
    )
    return proc.stdout, proc.stderr.decode("utf-8", errors="replace"), proc.returncode


def assert_budgets_match(
    testcase: unittest.TestCase,
    fixtures: dict,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Symmetric check: every fixture has a budget AND every budget has a fixture."""
    fixture_names = set(fixtures)
    budget_names = set(budgets)
    missing = fixture_names - budget_names
    extra = budget_names - fixture_names
    testcase.assertFalse(
        missing,
        f"{label} fixtures without a budget entry: {sorted(missing)}",
    )
    testcase.assertFalse(
        extra,
        f"budget entries with no matching {label} fixture: {sorted(extra)}",
    )


def assert_emitter_under_budgets(
    testcase: unittest.TestCase,
    scripts_dir: Path,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every emitter's stdout (run via fixture) must be at or below budget.

    Bootstraps one SMM per call and reuses it across all emitters.
    `subagent_stop.py` runs LAST because its xp-plan-reviewer fixture
    writes a real .assign-pending marker; running it last keeps the
    marker out of any sibling emitter's view.
    """
    import tempfile

    offenders: list[str] = []
    items = sorted(
        budgets.items(),
        key=lambda kv: (kv[0] == "subagent_stop.py", kv[0]),
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        for name, budget in items:
            stdout_bytes, stderr, rc = _run_emitter(name, scripts_dir, smm_dir, repo)
            if rc != 0:
                offenders.append(f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}")
                continue
            actual = len(stdout_bytes)
            if actual > budget:
                offenders.append(f"{name}: {actual} bytes (budget {budget})")
    testcase.assertFalse(
        offenders,
        f"{label} stdout exceeds budget:\n" + "\n".join(offenders),
    )


def discover_emitter_scripts(scripts_dir: Path) -> list[str]:
    """Walk scripts_dir for .py files that emit context via _common.hook_output.

    Surface-scan helper: returns sorted basenames of every script that calls
    `_common.hook_output(...)` anywhere in its source. Catches the gap where
    a new emitter ships without a fixture/budget entry. Substring match —
    keep the literal `_common.hook_output(` out of non-emitter docstrings.
    """
    return sorted(
        path.name
        for path in scripts_dir.glob("*.py")
        if "_common.hook_output(" in path.read_text(encoding="utf-8")
    )


# Single source of truth for preload-equivalent script names per skill.
# Default is "preload.sh"; only skills with an exception are listed here.
_PRELOAD_SCRIPT_NAME_OVERRIDES: dict[str, str] = {
    "xp-kickoff": "check_session_needs.sh",
}


def _preload_script_name(skill_name: str) -> str:
    return _PRELOAD_SCRIPT_NAME_OVERRIDES.get(skill_name, "preload.sh")


def discover_preload_scripts() -> list[str]:
    """Walk skills/*/scripts/ for preload-emitter scripts.

    Surface-scan helper: returns sorted skill names for every preload-equivalent
    script under `_PLUGIN_ROOT/skills/<name>/scripts/`. Catches the gap where
    a new preload ships without a fixture/budget entry.
    """
    skills_dir = _PLUGIN_ROOT / "skills"
    return sorted(
        skill_dir.name
        for skill_dir in skills_dir.iterdir()
        if skill_dir.is_dir()
        and (skill_dir / "scripts" / _preload_script_name(skill_dir.name)).is_file()
    )


def _preload_script_path(skill_name: str) -> Path:
    return (
        _PLUGIN_ROOT
        / "skills"
        / skill_name
        / "scripts"
        / _preload_script_name(skill_name)
    )


def _run_preload(
    skill_name: str,
    smm_dir: Path,
    cwd: Path,
) -> tuple[bytes, str, int]:
    """Run a preload.sh via subprocess against a pre-seeded SMM.

    Caller owns smm_dir + cwd lifecycle so multiple preload invocations
    can share one bootstrap (the budget test runs all preloads against
    the same empty SMM). Builder returns env-var dict (preloads read
    env vars set by the orchestrator); base SMM_DIR + CLAUDE_PLUGIN_ROOT
    + XP_TEAMMATE_NAME are injected here, builder additions merge on top.
    """
    import subprocess

    builder = PRELOAD_FIXTURES.get(skill_name)
    if builder is None:
        raise KeyError(f"no fixture builder registered for {skill_name}")

    env = os.environ.copy()
    env["SMM_DIR"] = str(smm_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    env["XP_TEAMMATE_NAME"] = ""
    for ev in _LEAKY_GIT_ENV:
        env.pop(ev, None)
    env.update(builder())
    proc = subprocess.run(
        [str(_preload_script_path(skill_name))],
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=15,
    )
    return proc.stdout, proc.stderr.decode("utf-8", errors="replace"), proc.returncode


def assert_preload_under_budgets(
    testcase: unittest.TestCase,
    budgets: dict[str, int],
    label: str,
) -> None:
    """Every preload's stdout (run via fixture) must be at or below budget.

    Bootstraps one SMM per call and reuses it across all preloads.
    """
    import tempfile

    offenders: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo, smm_dir = _bootstrap_seeded_smm(Path(tmp))
        for name, budget in sorted(budgets.items()):
            stdout_bytes, stderr, rc = _run_preload(name, smm_dir, repo)
            if rc != 0:
                offenders.append(f"{name}: subprocess rc={rc} stderr={stderr[:200]!r}")
                continue
            actual = len(stdout_bytes)
            if actual > budget:
                offenders.append(f"{name}: {actual} bytes (budget {budget})")
    testcase.assertFalse(
        offenders,
        f"{label} stdout exceeds budget:\n" + "\n".join(offenders),
    )


def assert_no_12hex_ids_in_md(
    testcase: unittest.TestCase,
    dir_path: Path,
    pattern: str,
    label: str,
) -> None:
    """Shipped text files must not contain 12-hex SMM event IDs.

    Generic across file types — `_in_md` is the historical name (M-1
    skills, M-2 agents); M-3 emitters call this with a `*.py` glob.
    """
    offenders: list[str] = []
    for path in dir_path.glob(pattern):
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _HISTORICAL_ID_RE.search(line):
                rel = path.relative_to(_PLUGIN_ROOT)
                offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
    testcase.assertFalse(
        offenders,
        f"12-hex IDs (decision/concern/event refs) in shipped {label} prose:\n"
        + "\n".join(offenders[:30]),
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
