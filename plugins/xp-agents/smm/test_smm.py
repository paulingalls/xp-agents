#!/usr/bin/env python3
"""Tests for SMM Foundation (Milestone 1).

Tests init.sh, append.sh, _append_impl.py, and schema.json.
Run with: python3 -m pytest smm/test_smm.py -v  (or just python3 smm/test_smm.py)
"""

import concurrent.futures
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Allow importing _append_impl from the same directory
sys.path.insert(0, str(Path(__file__).parent))
import _append_impl

ROOT = Path(__file__).resolve().parent.parent
INIT_SH = ROOT / "smm" / "init.sh"
APPEND_SH = ROOT / "smm" / "append.sh"


class _TempRepoTestCase(unittest.TestCase):
    """Base class: creates an isolated temp git repo per test class.

    Prevents subprocess tests (init.sh, append.sh) from touching the real SMM.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = Path(tempfile.mkdtemp())
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
        # Clean up the SMM project dir created under ~/.claude/xp-agents/<hash>/
        smm_dir = getattr(cls, "_smm_dir_cache", None)
        if smm_dir is not None:
            shutil.rmtree(smm_dir.parent, ignore_errors=True)
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _run_init(cls) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(INIT_SH)], capture_output=True, text=True, cwd=str(cls.tmpdir)
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
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
        return subprocess.run(
            [str(APPEND_SH), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cls.tmpdir),
        )


class TestInit(_TempRepoTestCase):
    """Tests for smm/init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def setUp(self) -> None:
        # Reset events.jsonl before each test to prevent state leakage
        (self.smm_dir / "events.jsonl").write_text("")

    def test_init_succeeds(self):
        result = self._run_init()
        self.assertEqual(result.returncode, 0)
        smm_dir = result.stdout.strip()
        self.assertTrue(Path(smm_dir).is_dir())

    def test_init_idempotent(self):
        r1 = self._run_init()
        r2 = self._run_init()
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_init_creates_structure(self):
        smm_dir = self._get_smm_dir()
        self.assertTrue((smm_dir / "events.jsonl").exists())
        self.assertTrue((smm_dir / "events.lock").exists())
        self.assertTrue((smm_dir / "retrospectives").is_dir())

    def test_init_events_file_permissions(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        mode = events_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.jsonl mode is {oct(mode)}")

    def test_init_lock_file_permissions(self):
        smm_dir = self._get_smm_dir()
        lock_file = smm_dir / "events.lock"
        mode = lock_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.lock mode is {oct(mode)}")

    def test_init_smm_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        mode = smm_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"SMM dir mode is {oct(mode)}")

    def test_init_retrospectives_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        retro_dir = smm_dir / "retrospectives"
        mode = retro_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"retrospectives dir mode is {oct(mode)}")

    def test_init_does_not_truncate_existing(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        events_file.write_text("existing content\n")

        self._run_init()

        self.assertEqual(events_file.read_text(), "existing content\n")


class TestValidateEvent(unittest.TestCase):
    """Tests for _append_impl.validate_event (unit tests, no subprocess)."""

    def _base_event(self, **overrides) -> dict:
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        event.update(overrides)
        return event

    def test_valid_customer_input(self):
        errors = _append_impl.validate_event(self._base_event())
        self.assertEqual(errors, [])

    def test_valid_status(self):
        event = self._base_event(type="status", working_on=["src/app.ts"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_decision(self):
        event = self._base_event(type="decision", topic="database")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_convention(self):
        event = self._base_event(type="convention", topic="naming")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_concern_with_severity(self):
        event = self._base_event(type="concern", severity="high")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_concern_without_severity(self):
        event = self._base_event(type="concern")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_discovery(self):
        event = self._base_event(type="discovery")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_question(self):
        event = self._base_event(type="question", priority="\U0001f534")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_answer(self):
        event = self._base_event(type="answer", references=["some-id"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_assumption(self):
        event = self._base_event(type="assumption")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_pair_guidance(self):
        event = self._base_event(type="pair_guidance", tool_name="Write")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_session_end_minimal(self):
        event = self._base_event(type="session_end")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_session_end_full(self):
        event = self._base_event(
            type="session_end",
            duration_seconds=3600.5,
            event_count=42,
            unresolved_items=["q1"],
            working_on=["file.py"],
            final_status_recorded=True,
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_retrospective(self):
        event = self._base_event(
            type="retrospective",
            keep=[{"content": "Good TDD", "values": ["feedback"]}],
            fix=[{"content": "Slow reviews", "xp_value": "communication"}],
        )
        event["try"] = [{"content": "Mob programming"}]
        self.assertEqual(_append_impl.validate_event(event), [])

    # --- Missing required fields ---

    def test_missing_universal_field(self):
        event = self._base_event()
        del event["agent_id"]
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("agent_id" in e for e in errors))

    def test_invalid_type(self):
        event = self._base_event(type="invalid")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("Invalid event type" in e for e in errors))

    def test_status_missing_working_on(self):
        event = self._base_event(type="status")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("working_on" in e for e in errors))

    def test_decision_missing_topic(self):
        event = self._base_event(type="decision")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("topic" in e for e in errors))

    def test_convention_missing_topic(self):
        event = self._base_event(type="convention")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("topic" in e for e in errors))

    def test_question_missing_priority(self):
        event = self._base_event(type="question")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("priority" in e for e in errors))

    def test_pair_guidance_missing_tool_name(self):
        event = self._base_event(type="pair_guidance")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("tool_name" in e for e in errors))

    # --- Invalid field values ---

    def test_invalid_severity(self):
        event = self._base_event(type="concern", severity="critical")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("severity" in e for e in errors))

    def test_invalid_priority(self):
        event = self._base_event(type="question", priority="urgent")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("priority" in e for e in errors))

    def test_working_on_wrong_type(self):
        event = self._base_event(type="status", working_on="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("array" in e for e in errors))

    def test_references_wrong_type(self):
        event = self._base_event(references="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_retrospective_keep_missing_content(self):
        event = self._base_event(type="retrospective", keep=[{"values": ["x"]}])
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("content" in e for e in errors))

    # --- New M5.2 types: goal, debt, customer_intent ---

    def test_valid_goal(self):
        event = self._base_event(type="goal")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_debt(self):
        event = self._base_event(type="debt", files=["src/legacy.py"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_debt_missing_files(self):
        event = self._base_event(type="debt")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("files" in e for e in errors))

    def test_debt_files_wrong_type(self):
        event = self._base_event(type="debt", files="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("array" in e for e in errors))

    def test_valid_customer_intent(self):
        event = self._base_event(type="customer_intent", intent_status="open")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_customer_intent_missing_intent_status(self):
        event = self._base_event(type="customer_intent")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("intent_status" in e for e in errors))

    def test_customer_intent_invalid_intent_status(self):
        event = self._base_event(type="customer_intent", intent_status="invalid")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("intent_status" in e for e in errors))

    def test_customer_intent_all_statuses_valid(self):
        for status in ("open", "delivered", "superseded"):
            with self.subTest(status=status):
                event = self._base_event(type="customer_intent", intent_status=status)
                self.assertEqual(_append_impl.validate_event(event), [])

    # --- All three priority emojis ---

    def test_priority_red(self):
        event = self._base_event(type="question", priority="\U0001f534")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_priority_yellow(self):
        event = self._base_event(type="question", priority="\U0001f7e1")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_priority_green(self):
        event = self._base_event(type="question", priority="\U0001f7e2")
        self.assertEqual(_append_impl.validate_event(event), [])


class TestAppendIntegration(_TempRepoTestCase):
    """Integration tests using append.sh subprocess."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()
        cls.events_file = cls.smm_dir / "events.jsonl"

    def setUp(self):
        # Clear events before each test
        self.events_file.write_text("")

    def _read_events(self) -> list[dict]:
        lines = self.events_file.read_text().strip().split("\n")
        return [json.loads(line) for line in lines if line]

    def test_append_status(self):
        r = self._run_append(
            "--type",
            "status",
            "--agent",
            "main",
            "--content",
            "working",
            "--working-on",
            '["f.py"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "status")
        self.assertEqual(events[0]["working_on"], ["f.py"])

    def test_append_question_with_emoji(self):
        r = self._run_append(
            "--type",
            "question",
            "--agent",
            "main",
            "--content",
            "Which DB?",
            "--priority",
            "\U0001f534",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["priority"], "\U0001f534")

    def test_append_decision_with_topic(self):
        r = self._run_append(
            "--type",
            "decision",
            "--agent",
            "main",
            "--content",
            "Use Postgres",
            "--topic",
            "database",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["topic"], "database")

    def test_append_with_references(self):
        r = self._run_append(
            "--type",
            "answer",
            "--agent",
            "main",
            "--content",
            "Yes",
            "--references",
            '["id-1","id-2"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["references"], ["id-1", "id-2"])

    def test_reject_invalid_type(self):
        r = self._run_append("--type", "invalid", "--agent", "main", "--content", "bad")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_working_on(self):
        r = self._run_append("--type", "status", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_topic(self):
        r = self._run_append("--type", "decision", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_priority(self):
        r = self._run_append("--type", "question", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_tool_name(self):
        r = self._run_append(
            "--type", "pair_guidance", "--agent", "main", "--content", "x"
        )
        self.assertNotEqual(r.returncode, 0)

    def test_event_has_uuid_and_timestamp(self):
        r = self._run_append(
            "--type", "discovery", "--agent", "main", "--content", "found it"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        event = events[0]
        # UUID v4 format
        self.assertRegex(
            event["id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        # ISO 8601 with timezone
        self.assertIn("T", event["ts"])
        self.assertIn("+", event["ts"])

    def test_all_15_types_succeed(self):
        """Ensure every event type can be appended with valid arguments."""
        cases = [
            ["--type", "customer_input", "--agent", "m", "--content", "x"],
            [
                "--type",
                "customer_intent",
                "--agent",
                "m",
                "--content",
                "x",
                "--intent-status",
                "open",
            ],
            [
                "--type",
                "debt",
                "--agent",
                "m",
                "--content",
                "x",
                "--files",
                '["src/legacy.py"]',
            ],
            ["--type", "goal", "--agent", "m", "--content", "x"],
            [
                "--type",
                "status",
                "--agent",
                "m",
                "--content",
                "x",
                "--working-on",
                '["f"]',
            ],
            ["--type", "decision", "--agent", "m", "--content", "x", "--topic", "t"],
            ["--type", "convention", "--agent", "m", "--content", "x", "--topic", "t"],
            ["--type", "concern", "--agent", "m", "--content", "x"],
            ["--type", "discovery", "--agent", "m", "--content", "x"],
            [
                "--type",
                "question",
                "--agent",
                "m",
                "--content",
                "x",
                "--priority",
                "\U0001f7e1",
            ],
            ["--type", "answer", "--agent", "m", "--content", "x"],
            ["--type", "assumption", "--agent", "m", "--content", "x"],
            [
                "--type",
                "pair_guidance",
                "--agent",
                "m",
                "--content",
                "x",
                "--tool-name",
                "Write",
            ],
            ["--type", "session_end", "--agent", "m", "--content", "x"],
            ["--type", "retrospective", "--agent", "m", "--content", "x"],
        ]
        for args in cases:
            with self.subTest(type=args[1]):
                r = self._run_append(*args)
                self.assertEqual(r.returncode, 0, f"Failed for {args[1]}: {r.stderr}")

        events = self._read_events()
        types = {e["type"] for e in events}
        self.assertEqual(len(types), 15, f"Expected 15 types, got {types}")

    def test_session_end_optional_fields(self):
        r = self._run_append(
            "--type",
            "session_end",
            "--agent",
            "main",
            "--content",
            "done",
            "--duration-seconds",
            "3600.5",
            "--event-count",
            "42",
            "--working-on",
            '["f.py"]',
            "--final-status-recorded",
            "true",
            "--unresolved-items",
            '["q1"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        e = events[0]
        self.assertEqual(e["duration_seconds"], 3600.5)
        self.assertEqual(e["event_count"], 42)
        self.assertEqual(e["working_on"], ["f.py"])
        self.assertTrue(e["final_status_recorded"])
        self.assertEqual(e["unresolved_items"], ["q1"])

    def test_retrospective_nested_objects(self):
        keep = json.dumps(
            [{"content": "Good TDD", "event_refs": ["e1"], "values": ["feedback"]}]
        )
        fix = json.dumps(
            [{"content": "Slow", "event_refs": ["e2"], "xp_value": "communication"}]
        )
        try_items = json.dumps([{"content": "Mob", "event_refs": ["e3"]}])
        r = self._run_append(
            "--type",
            "retrospective",
            "--agent",
            "main",
            "--content",
            "review",
            "--keep",
            keep,
            "--fix",
            fix,
            "--try-items",
            try_items,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        e = events[0]
        self.assertEqual(e["keep"][0]["content"], "Good TDD")
        self.assertEqual(e["fix"][0]["xp_value"], "communication")
        self.assertEqual(e["try"][0]["content"], "Mob")


class TestAnsiStripping(unittest.TestCase):
    """Test that ANSI escape codes are stripped from event content at write time."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        (self.smm_dir / "events.jsonl").touch()
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        shutil.rmtree(self.smm_dir)

    def test_ansi_stripped_from_content(self):
        """ANSI escape codes should be removed from content field."""
        event = {
            "id": "test-id",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "concern",
            "agent_id": "main",
            "content": "\x1b[31mError:\x1b[0m something \x1b[1;32mfailed\x1b[0m",
            "schema_version": 1,
        }
        _append_impl.append_event(self.smm_dir, event)
        line = (self.smm_dir / "events.jsonl").read_text().strip()
        written = json.loads(line)
        self.assertEqual(written["content"], "Error: something failed")
        self.assertNotIn("\x1b", written["content"])

    def test_content_without_ansi_unchanged(self):
        """Content without ANSI codes should pass through unchanged."""
        event = {
            "id": "test-id-2",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "status",
            "agent_id": "main",
            "content": "Normal text without escapes",
            "working_on": ["app.py"],
            "schema_version": 1,
        }
        _append_impl.append_event(self.smm_dir, event)
        line = (self.smm_dir / "events.jsonl").read_text().strip()
        written = json.loads(line)
        self.assertEqual(written["content"], "Normal text without escapes")


class TestLockTimeout(unittest.TestCase):
    """Test that lock timeout raises instead of degrading."""

    def test_append_fails_on_lock_timeout(self):
        """If the lock can't be acquired, append should raise, not silently continue."""
        import tempfile

        smm_dir = Path(tempfile.mkdtemp())
        events_file = smm_dir / "events.jsonl"
        lock_file = smm_dir / "events.lock"
        events_file.touch()
        lock_file.touch()

        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }

        # Hold an exclusive lock so append_event can't acquire it
        lock_fd = open(lock_file, "a")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with self.assertRaises(_append_impl.LockTimeoutError):
                _append_impl.append_event(smm_dir, event)
            # File should be unchanged — no write without lock
            self.assertEqual(events_file.read_text(), "")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            import shutil

            shutil.rmtree(smm_dir)


class TestConcurrentWrites(_TempRepoTestCase):
    """Test atomic append under concurrent load."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def test_20_concurrent_writes(self):
        events_file = self.smm_dir / "events.jsonl"
        events_file.write_text("")

        def do_append(i: int) -> int:
            r = self._run_append(
                "--type",
                "status",
                "--agent",
                f"test-{i}",
                "--content",
                f"concurrent {i}",
                "--working-on",
                '["f.py"]',
            )
            return r.returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(do_append, i) for i in range(1, 21)]
            codes = [f.result() for f in futures]

        self.assertTrue(all(c == 0 for c in codes), f"Some appends failed: {codes}")

        lines = events_file.read_text().strip().split("\n")
        self.assertEqual(len(lines), 20, f"Expected 20 lines, got {len(lines)}")

        # All valid JSON
        events = []
        for i, line in enumerate(lines, 1):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON on line {i}")

        # All unique agent_ids
        agents = {e["agent_id"] for e in events}
        self.assertEqual(
            len(agents), 20, f"Expected 20 unique agents, got {len(agents)}"
        )


class TestAgentIdValidation(unittest.TestCase):
    """Tests for _append_impl._validate_agent_id allowlist."""

    def test_accepts_simple_name(self):
        _append_impl._validate_agent_id("main")

    def test_accepts_hyphenated(self):
        _append_impl._validate_agent_id("xp-navigator")

    def test_accepts_colon_separator(self):
        _append_impl._validate_agent_id("xp-quality:reviewer")

    def test_accepts_underscore(self):
        _append_impl._validate_agent_id("test_agent")

    def test_accepts_digits(self):
        _append_impl._validate_agent_id("agent123")

    def test_rejects_semicolon(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent;rm -rf")

    def test_rejects_backtick(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent`cmd`")

    def test_rejects_pipe(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent|cat")

    def test_rejects_dollar(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent$HOME")

    def test_rejects_space(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent name")

    def test_rejects_slash(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("../escape")

    def test_rejects_null(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent\x00id")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("")


class TestSmmDirValidation(unittest.TestCase):
    """Tests for SMM directory ownership validation."""

    def setUp(self):
        import tempfile

        self.smm_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        if self.smm_dir.exists():
            self.smm_dir.chmod(0o700)
            shutil.rmtree(self.smm_dir)

    def test_rejects_nonexistent(self):
        import shutil

        shutil.rmtree(self.smm_dir)
        with self.assertRaises(ValueError):
            _append_impl._validate_smm_dir(self.smm_dir)

    def test_rejects_world_writable(self):
        self.smm_dir.chmod(0o777)
        with self.assertRaises(ValueError):
            _append_impl._validate_smm_dir(self.smm_dir)

    def test_accepts_valid_dir(self):
        self.smm_dir.chmod(0o700)
        _append_impl._validate_smm_dir(self.smm_dir)


class TestSymlinkProtection(unittest.TestCase):
    """Tests that symlinks at lock/event paths are rejected."""

    def setUp(self):
        import tempfile

        self.smm_dir = Path(tempfile.mkdtemp())
        (self.smm_dir / "events.jsonl").touch()
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.smm_dir)

    def test_symlink_at_lock_file_rejected(self):
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock")
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        with self.assertRaises(OSError):
            _append_impl.append_event(self.smm_dir, event)

    def test_symlink_at_events_file_rejected(self):
        events_file = self.smm_dir / "events.jsonl"
        events_file.unlink()
        events_file.symlink_to("/tmp/decoy-events")
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        with self.assertRaises(OSError):
            _append_impl.append_event(self.smm_dir, event)


class TestJsonSizeLimit(unittest.TestCase):
    """Test that oversized JSON args are rejected."""

    def test_oversized_json_rejected(self):
        huge = '["' + "x" * 70000 + '"]'
        with self.assertRaises(SystemExit) as cm:
            _append_impl.parse_json_arg(huge, "references")
        self.assertEqual(cm.exception.code, 1)

    def test_normal_json_accepted(self):
        result = _append_impl.parse_json_arg('["a","b"]', "references")
        self.assertEqual(result, ["a", "b"])


class TestSchemaJson(unittest.TestCase):
    """Validate schema.json structure itself."""

    @classmethod
    def setUpClass(cls):
        schema_path = ROOT / "smm" / "schema.json"
        with open(schema_path) as f:
            cls.schema = json.load(f)

    def test_schema_is_valid_json(self):
        self.assertIsInstance(self.schema, dict)

    def test_schema_has_16_types(self):
        types = self.schema["properties"]["type"]["enum"]
        self.assertEqual(len(types), 16)
        expected = {
            "customer_input",
            "customer_intent",
            "debt",
            "goal",
            "status",
            "decision",
            "convention",
            "concern",
            "discovery",
            "question",
            "answer",
            "assumption",
            "pair_guidance",
            "session_end",
            "retrospective",
            "security_review_requested",
        }
        self.assertEqual(set(types), expected)

    def test_universal_required_fields(self):
        required = self.schema["required"]
        for field in ("id", "ts", "type", "agent_id", "content"):
            self.assertIn(field, required)

    def test_type_specific_properties_at_top_level(self):
        """Verify type-specific properties are in top-level properties
        (not buried in allOf/then), so additionalProperties: false works."""
        top_props = self.schema["properties"]
        for field in (
            "working_on",
            "topic",
            "severity",
            "priority",
            "tool_name",
            "duration_seconds",
            "event_count",
            "unresolved_items",
            "final_status_recorded",
            "keep",
            "fix",
            "try",
            "files",
            "intent_status",
        ):
            self.assertIn(
                field, top_props, f"'{field}' must be in top-level properties"
            )

    def test_additional_properties_false(self):
        self.assertFalse(self.schema["additionalProperties"])

    def test_conditional_required_fields(self):
        """Verify allOf contains conditional required constraints."""
        all_of = self.schema["allOf"]
        # Find the required fields imposed by conditionals
        conditional_reqs = {}
        for entry in all_of:
            if_clause = entry.get("if", {}).get("properties", {}).get("type", {})
            then_clause = entry.get("then", {})
            type_match = if_clause.get("const") or if_clause.get("enum", [None])
            required = then_clause.get("required", [])
            if required:
                if isinstance(type_match, list):
                    for t in type_match:
                        conditional_reqs[t] = required
                else:
                    conditional_reqs[type_match] = required

        self.assertIn("working_on", conditional_reqs.get("status", []))
        self.assertIn("topic", conditional_reqs.get("decision", []))
        self.assertIn("topic", conditional_reqs.get("convention", []))
        self.assertIn("priority", conditional_reqs.get("question", []))
        self.assertIn("tool_name", conditional_reqs.get("pair_guidance", []))
        self.assertIn("files", conditional_reqs.get("debt", []))
        self.assertIn("intent_status", conditional_reqs.get("customer_intent", []))


# ===========================================================================
# Notification tests — Milestone 3.4
# ===========================================================================


class TestNotificationHelpers(unittest.TestCase):
    """Test _detect_platform, _sanitize_notification, _notify_blocking_question."""

    def test_detect_platform_macos(self):
        with patch("_append_impl.sys") as mock_sys:
            mock_sys.platform = "darwin"
            self.assertEqual(_append_impl._detect_platform(), "macos")

    def test_detect_platform_linux(self):
        with patch("_append_impl.sys") as mock_sys:
            mock_sys.platform = "linux"
            self.assertEqual(_append_impl._detect_platform(), "linux")

    def test_detect_platform_unknown(self):
        with patch("_append_impl.sys") as mock_sys:
            mock_sys.platform = "win32"
            self.assertEqual(_append_impl._detect_platform(), "unknown")

    def test_sanitize_strips_quotes(self):
        result = _append_impl._sanitize_notification('He said "hello"')
        self.assertNotIn('"', result)

    def test_sanitize_strips_backslashes(self):
        result = _append_impl._sanitize_notification("path\\to\\file")
        self.assertNotIn("\\", result)

    def test_sanitize_limits_length(self):
        result = _append_impl._sanitize_notification("x" * 300)
        self.assertLessEqual(len(result), 200)

    def test_macos_notification_command(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("_append_impl._detect_platform", return_value="macos"),
            patch("_append_impl.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "osascript")

    def test_linux_notification_command(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("_append_impl._detect_platform", return_value="linux"),
            patch("_append_impl.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "notify-send")

    def test_non_red_question_no_notification(self):
        event = {
            "type": "question",
            "priority": "\U0001f7e1",
            "content": "Minor question",
        }
        with patch("_append_impl.subprocess.run") as mock_run:
            _append_impl._notify_blocking_question(event)
            mock_run.assert_not_called()

    def test_non_question_no_notification(self):
        event = {
            "type": "status",
            "working_on": ["file.py"],
            "content": "Working",
        }
        with patch("_append_impl.subprocess.run") as mock_run:
            _append_impl._notify_blocking_question(event)
            mock_run.assert_not_called()

    def test_notification_failure_doesnt_crash(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("_append_impl._detect_platform", return_value="macos"),
            patch(
                "_append_impl.subprocess.run",
                side_effect=OSError("no osascript"),
            ),
        ):
            # Should not raise
            _append_impl._notify_blocking_question(event)

    def test_message_sanitized(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": 'He said "drop tables\\n"',
        }
        with (
            patch("_append_impl._detect_platform", return_value="macos"),
            patch("_append_impl.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            # The notification message should not contain quotes or backslashes
            args = mock_run.call_args[0][0]
            # osascript -e 'display notification "..." with title "XP Agents"'
            script = args[2]  # the -e argument value
            # Should not contain raw quotes in the notification text
            self.assertNotIn("drop tables\\n", script)


if __name__ == "__main__":
    unittest.main()
