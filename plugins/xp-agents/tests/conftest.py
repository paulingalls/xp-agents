#!/usr/bin/env python3
"""Shared test helpers for all xp-agents test suites.

Provides base test cases and factory functions used across hook, integration,
engine, and SMM tests. Import from here instead of cross-importing between
test files.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from collections.abc import Sequence
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow importing production modules
# ---------------------------------------------------------------------------

_PLUGIN_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = _PLUGIN_ROOT / "scripts"
_SMM_DIR = _PLUGIN_ROOT / "smm"

sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SMM_DIR))


# ---------------------------------------------------------------------------
# Sprint fixtures — shared across test_accept.py, test_pre_tool_write.py, etc.
# ---------------------------------------------------------------------------

SPRINT_IN_PROGRESS = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** in-progress
- **Dependencies:** none
"""

SPRINT_READY_ONLY = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** ready
- **Dependencies:** none
"""

SPRINT_ALL_DONE = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done

### story-002: As a user I can register
- **Size:** S
- **Status:** deferred
"""

SPRINT_MIXED = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: As a user I can register
- **Size:** S
- **Status:** ready
- **Dependencies:** none

### story-003: As an admin I can list users
- **Size:** L
- **Status:** ready
- **Dependencies:** story-002
"""

SPRINT_MIXED_IN_PROGRESS = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: As a user I can register
- **Size:** S
- **Status:** in-progress
- **Dependencies:** none
"""


# ---------------------------------------------------------------------------
# Event factory
# ---------------------------------------------------------------------------


def make_event(event_type: str = "customer_input", **kwargs) -> dict:
    """Create a valid event dict with defaults."""
    event = {
        "id": str(uuid.uuid4()),
        "ts": "2026-03-12T00:00:00+00:00",
        "type": event_type,
        "agent_id": "main",
        "content": "test content",
        "schema_version": 1,
    }
    match event_type:
        case "status":
            event["working_on"] = kwargs.pop("working_on", ["src/app.ts"])
        case "decision" | "convention":
            event["topic"] = kwargs.pop("topic", "default-topic")
        case "question":
            event["priority"] = kwargs.pop("priority", "\U0001f534")
        case "goal":
            pass  # No extra required fields
        case "debt":
            event["files"] = kwargs.pop("files", ["src/legacy.py"])
        case "customer_intent":
            event["intent_status"] = kwargs.pop("intent_status", "open")
        case "sprint":
            event["metadata"] = kwargs.pop(
                "metadata", {"sprint_id": "sprint-001", "action": "start"}
            )
    event.update(kwargs)
    return event


# ---------------------------------------------------------------------------
# Base test cases
# ---------------------------------------------------------------------------


class _SMMTestCase(unittest.TestCase):
    """Base test case that creates a temp SMM directory."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        self.events_file = self.smm_dir / "events.jsonl"
        (self.smm_dir / "events.lock").touch()
        self.events_file.touch()

    def tearDown(self):
        shutil.rmtree(self.smm_dir)

    def _write_events(self, events: list[dict]) -> None:
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        self.events_file.write_text("\n".join(lines) + ("\n" if lines else ""))

    def _write_raw_lines(self, lines: list[str]) -> None:
        self.events_file.write_text("\n".join(lines) + "\n")

    def _read_events(self) -> list[dict]:
        """Read events back from events.jsonl, skipping empty/bad lines."""
        events = []
        for line in self.events_file.read_text().splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


# Alias used by hook tests
_HookTestCase = _SMMTestCase


def write_smm_fixture(
    smm_dir: Path,
    *,
    intent: "Sequence[tuple[str, str]] | None" = None,
    constraints: "Sequence[tuple[str, str]] | None" = None,
    risks: "Sequence[tuple[str, str, str]] | None" = None,
    wisdom: "Sequence[str] | None" = None,
) -> None:
    """Build and save an SMM JSON fixture.

    Args:
        smm_dir: SMM directory path.
        intent: List of (content, type) tuples — type is "goal" or "customer_intent".
        constraints: (content, type) tuples — "decision" or "convention".
        risks: List of (content, type, severity) tuples.
        wisdom: List of content strings.
    """
    import smm_store

    def _make(content: str, **extra: str) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "content": content,
            "source": "seed",
            "ts": "2026-01-01T00:00:00+00:00",
            **extra,
        }

    data: dict = {
        "intent": [_make(c, type=t) for c, t in (intent or [])],
        "constraints": [_make(c, type=t) for c, t in (constraints or [])],
        "risks": [_make(c, type=t, severity=s) for c, t, s in (risks or [])],
        "wisdom": [_make(c) for c in (wisdom or [])],
    }
    smm_store.save_smm(smm_dir, data)


# ---------------------------------------------------------------------------
# Hook input factories
# ---------------------------------------------------------------------------


def _make_write_input(**overrides) -> dict:
    """Build a canonical Write tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Write",
        "tool_input": {"file_path": "src/app.ts", "content": "x"},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_bash_input(command: str = "echo hi", stdout: str = "", **overrides) -> dict:
    """Build a canonical Bash tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_skill_input(skill: str = "test-skill", **overrides) -> dict:
    """Build a canonical Skill tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Skill",
        "tool_input": {"skill": skill},
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input dict."""
    data = {"session_id": "t", "agent_id": "main"}
    data.update(overrides)
    return data


def _make_teammate_idle_input(**overrides) -> dict:
    """Build a canonical TeammateIdle hook input dict."""
    data = {
        "session_id": "t",
        "teammate_name": "worker-1",
        "team_name": "test-team",
        "permission_mode": "bypassPermissions",
    }
    data.update(overrides)
    return data


def _make_task_completed_input(**overrides) -> dict:
    """Build a canonical TaskCompleted hook input dict."""
    data = {
        "session_id": "t",
        "task_id": "task-1",
        "task_subject": "Implement feature",
        "task_description": "Build the thing",
        "teammate_name": "worker-1",
        "team_name": "test-team",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Integration test base
# ---------------------------------------------------------------------------


class _IntegrationTestCase(unittest.TestCase):
    """Base class that creates a temp git repo and inits SMM via init.sh."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # Create a git repo
        subprocess.run(
            ["git", "init"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Need an initial commit so HEAD exists
        (self.tmpdir / "README").write_text("init")
        subprocess.run(
            ["git", "add", "README"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Init SMM — use a temp plugin data dir for test isolation
        self._plugin_data_dir = Path(tempfile.mkdtemp())
        self._test_env = os.environ.copy()
        self._test_env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)

        init_sh = _PLUGIN_ROOT / "smm" / "init.sh"
        result = subprocess.run(
            ["bash", str(init_sh)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=self._test_env,
        )
        self.smm_dir = Path(result.stdout.strip())
        self.scripts_dir = _SCRIPTS_DIR

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        shutil.rmtree(self._plugin_data_dir, ignore_errors=True)

    def _run_preload(
        self,
        script_path: Path,
        extra_env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a preload.sh script as a subprocess."""
        if not script_path.is_file():
            self.skipTest(f"Preload script not found: {script_path}")
        env = self._test_env.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(script_path)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_script(
        self, script_name: str, input_data: dict
    ) -> subprocess.CompletedProcess:
        """Run a hook script as a subprocess with JSON on stdin.

        Uses the same CLAUDE_PLUGIN_DATA as setUp so scripts resolve
        the same SMM path.
        """
        return subprocess.run(
            ["python3", str(self.scripts_dir / script_name)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )

    def _read_events(self) -> list[dict]:
        """Read events from the SMM events.jsonl."""
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        events = []
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _run_script_with_env(
        self, script_name: str, input_data: dict, env_overrides: dict
    ) -> subprocess.CompletedProcess:
        """Run a hook script with custom environment variables."""
        env = self._test_env.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["python3", str(self.scripts_dir / script_name)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=env,
        )

    def _seed_events(self, events: list[dict]) -> None:
        """Write seed events to events.jsonl."""
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        (self.smm_dir / "events.jsonl").write_text(
            "\n".join(lines) + ("\n" if lines else "")
        )


# ---------------------------------------------------------------------------
# SMM Foundation test base (subprocess-based, uses init.sh/append.sh)
# ---------------------------------------------------------------------------


class _TempRepoTestCase(unittest.TestCase):
    """Base class: creates an isolated temp git repo per test class.

    Prevents subprocess tests (init.sh, append.sh) from touching the real SMM.
    """

    _INIT_SH = _PLUGIN_ROOT / "smm" / "init.sh"
    _APPEND_SH = _PLUGIN_ROOT / "smm" / "append.sh"

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp())
        cls._plugin_data_dir = Path(tempfile.mkdtemp())
        cls._test_env = os.environ.copy()
        cls._test_env["CLAUDE_PLUGIN_DATA"] = str(cls._plugin_data_dir)
        subprocess.run(["git", "init"], cwd=cls.tmpdir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=cls.tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=cls.tmpdir,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._plugin_data_dir, ignore_errors=True)
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _run_init(cls) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(cls._INIT_SH)],
            capture_output=True,
            text=True,
            cwd=str(cls.tmpdir),
            env=cls._test_env,
        )

    @classmethod
    def _get_smm_dir(cls) -> Path:
        if not hasattr(cls, "_smm_dir_cache"):
            result = cls._run_init()
            assert result.returncode == 0, f"init.sh failed: {result.stderr}"
            cls._smm_dir_cache = Path(result.stdout.strip())
        return cls._smm_dir_cache

    @classmethod
    def _run_append(cls, *args: str) -> subprocess.CompletedProcess:
        env = cls._test_env.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
        return subprocess.run(
            [str(cls._APPEND_SH), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cls.tmpdir),
        )
