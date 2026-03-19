#!/usr/bin/env python3
"""Tests for PostToolUse, lint_check, bash_post_tool, and bash_failure hooks.

Split from the monolithic test_hooks.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import lint_check
import post_tool_use
from conftest import _HookTestCase, _make_bash_input, _make_write_input, make_event

# ===========================================================================
# post_tool_use.py tests — Milestone 3.3
# ===========================================================================


class TestPostToolUse(_HookTestCase):
    def test_auto_status_from_write(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        # Path is normalized against cwd
        self.assertIn("/tmp/src/app.ts", statuses[0]["working_on"])

    def test_auto_status_from_edit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_auto_status_from_multiedit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_normalizes_relative_path(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}, cwd="/home/user"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(statuses[0]["working_on"], ["/home/user/src/app.ts"])

    def test_xp_agent_skips(self):
        post_tool_use.run(
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        post_tool_use.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_conflict_working_on_overlap(self):
        # Another agent claims the same file
        self._write_events(
            [
                make_event("status", agent_id="other", working_on=["src/app.ts"]),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_conflict_stale_question(self):
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        self._write_events([q, *filler])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("stale" in c["content"].lower() for c in concerns))

    def test_conflict_superseded_decision(self):
        self._write_events(
            [
                make_event("decision", topic="db", content="Use Postgres"),
                make_event("decision", topic="db", content="Use MySQL"),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("superseded" in c["content"].lower() for c in concerns))

    def test_conflict_assumption_contradicted(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._write_events([a, d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_conflict_convention_violation(self):
        self._write_events(
            [
                make_event("convention", topic="naming", content="Use camelCase"),
                make_event("decision", topic="naming", content="Use snake_case"),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("convention" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [
                make_event("status", agent_id="main", working_on=["src/a.ts"]),
                make_event("decision", topic="db", content="Use Postgres"),
            ]
        )
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/b.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_semantic_references(self):
        # Decision references our file
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/auth.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/auth.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        refs = statuses[0].get("references", [])
        self.assertIn(d["id"], refs)

    def test_no_semantic_refs_unrelated(self):
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/other.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        refs = statuses[0].get("references", [])
        self.assertNotIn(d["id"], refs)


# ===========================================================================
# lint_check.py tests — Milestone 3.3
# ===========================================================================


class TestDetectLinterConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_detects_ruff_config(self):
        (self.tmpdir / "ruff.toml").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_detects_eslint_config(self):
        (self.tmpdir / ".eslintrc.json").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "eslint")

    def test_detects_pyproject_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_no_config_returns_none(self):
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNone(result)


class TestLintCheck(_HookTestCase):
    def test_no_config_warns_once(self):
        lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("linter", concerns[0]["content"].lower())
        # Flag file should exist
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

    def test_no_config_second_time_silent(self):
        (self.smm_dir / ".lint-warned").touch()
        lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_linter_binary_missing(self):
        # Create a ruff.toml in a temp dir but ruff isn't on PATH
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value=None):
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_clean_lint_no_event(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_errors_appends_concern(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {
                        "returncode": 1,
                        "stdout": "src/app.py:1:1: E302 expected 2 blank lines",
                        "stderr": "",
                    },
                )()
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 1)
            self.assertEqual(concerns[0].get("severity"), "medium")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_timeout(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.run_linter", return_value=None),
            ):
                lint_check.run(
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_xp_agent_skips(self):
        lint_check.run(
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        lint_check.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_ruff_skips_json_file(self):
        """ruff should not run against .json files — they are not Python."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value="/usr/bin/ruff"):
                result = lint_check.run_linter("ruff", str(tmpdir / "hooks.json"))
            self.assertIsNone(result)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_ruff_runs_on_python_file(self):
        """ruff should still run on .py files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                result = lint_check.run_linter("ruff", str(tmpdir / "app.py"))
            self.assertIsNone(result)  # clean — no errors
            mock_run.assert_called_once()
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_debounce_skips_recently_modified_file(self):
        """Lint is skipped if file mtime is less than 1 second ago."""
        tmpdir = Path(tempfile.mkdtemp())
        target = tmpdir / "app.py"
        target.write_text("x = 1\n")
        # File was just written — mtime is < 1s ago
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                result = lint_check.run_linter("ruff", str(target))
            self.assertIsNone(result)
            mock_run.assert_not_called()
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_no_debounce_for_old_file(self):
        """Lint runs normally if file mtime is more than 1 second ago."""
        import os
        import time

        tmpdir = Path(tempfile.mkdtemp())
        target = tmpdir / "app.py"
        target.write_text("x = 1\n")
        # Set mtime to 2 seconds ago
        old_time = time.time() - 2.0
        os.utime(str(target), (old_time, old_time))
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                lint_check.run_linter("ruff", str(target))
            mock_run.assert_called_once()
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)


# ===========================================================================
# bash_post_tool.py tests — Milestone 3.3
# ===========================================================================


class TestIsGitCommit(unittest.TestCase):
    def test_git_commit_m(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit -m 'msg'"))

    def test_git_commit_am(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit -am 'msg'"))

    def test_git_commit_with_path(self):
        self.assertTrue(bash_post_tool.is_git_commit("cd /tmp && git commit -m 'x'"))

    def test_not_git_status(self):
        self.assertFalse(bash_post_tool.is_git_commit("git status"))

    def test_not_ls(self):
        self.assertFalse(bash_post_tool.is_git_commit("ls -la"))

    def test_git_commit_no_message(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit"))


class TestIsTestRun(unittest.TestCase):
    def test_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("pytest"), "pytest")

    def test_python_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python -m pytest"), "pytest")

    def test_python3_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python3 -m pytest"), "pytest")

    def test_jest(self):
        self.assertEqual(bash_post_tool.is_test_run("npx jest"), "jest")

    def test_jest_bare(self):
        self.assertEqual(bash_post_tool.is_test_run("jest"), "jest")

    def test_go_test(self):
        self.assertEqual(bash_post_tool.is_test_run("go test ./..."), "go")

    def test_not_test(self):
        self.assertIsNone(bash_post_tool.is_test_run("ls -la"))

    def test_npm_test(self):
        self.assertEqual(bash_post_tool.is_test_run("npm test"), "jest")


class TestParseCommitMessage(unittest.TestCase):
    def test_standard_output(self):
        response = "[main abc123] Add auth module\n 3 files changed, 45 insertions(+)"
        result = bash_post_tool.parse_commit_message(response)
        self.assertEqual(result, "Add auth module")

    def test_no_match(self):
        result = bash_post_tool.parse_commit_message("error: something went wrong")
        self.assertIsNone(result)


class TestParseTestResults(unittest.TestCase):
    def test_pytest_pass(self):
        output = "===== 5 passed in 0.3s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_pytest_fail(self):
        output = "===== 3 passed, 2 failed in 1.2s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_jest_pass(self):
        output = "Tests:  5 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_jest_fail(self):
        output = "Tests:  2 failed, 3 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_go_pass(self):
        output = "ok  \tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)

    def test_go_fail(self):
        output = "--- FAIL: TestSomething (0.00s)\nFAIL\tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["failed"], 1)

    def test_unittest_pass(self):
        output = "Ran 821 tests in 32.346s\n\nOK"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 821)
        self.assertEqual(result["failed"], 0)

    def test_unittest_fail(self):
        output = "Ran 50 tests in 1.2s\n\nFAILED (failures=2, errors=1)"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 47)
        self.assertEqual(result["failed"], 3)
        self.assertEqual(result["errors"], 1)

    def test_is_test_run_unittest(self):
        self.assertEqual(
            bash_post_tool.is_test_run("python3 -m unittest tests/test_foo.py -v"),
            "unittest",
        )
        self.assertIsNone(bash_post_tool.is_test_run("echo unittest"))


class TestBashPostTool(_HookTestCase):
    def test_git_commit_auto_drafts_decision(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add auth'",
                    stdout="[main abc123] Add auth\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].get("metadata", {}).get("draft"))
        self.assertIn("Add auth", decisions[0]["content"])

    def test_git_commit_small_no_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main abc123] Fix bug\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_git_commit_large_appends_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=12):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Big change'",
                    stdout="[main abc123] Big change\n 12 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("12 files" in c["content"] for c in concerns))

    def test_commit_threshold_from_settings(self):
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        original = settings_path.read_text()
        try:
            settings_path.write_text(json.dumps({"commit_size_threshold": 5}))
            with patch("bash_post_tool.count_commit_files", return_value=6):
                bash_post_tool.run(
                    _make_bash_input(
                        command="git commit -m 'x'",
                        stdout="[main a] x\n 6 files changed",
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertTrue(len(concerns) >= 1)
        finally:
            settings_path.write_text(original)

    def test_commit_threshold_default(self):
        self.assertEqual(bash_post_tool.load_commit_threshold(), 10)

    def test_pytest_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("5 passed" in s["content"] for s in statuses))

    def test_pytest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 3 passed, 2 failed in 1.2s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            _make_bash_input(command="npx jest", stdout="Tests:  5 passed, 5 total"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_jest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="npx jest",
                stdout="Tests:  2 failed, 3 passed, 5 total",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="ok  \tgithub.com/user/pkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_go_test_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="--- FAIL: TestSomething (0.00s)\nFAIL\tpkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            _make_bash_input(command="ls -la", stdout="total 0"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips(self):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'x'",
                stdout="[main a] x",
                agent_type="xp-navigator",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        bash_post_tool.run(
            _make_bash_input(command="git commit -m 'x'", stdout="[main a] x"),
            smm_dir=fake_dir,
        )

    def test_git_commit_parse_message(self):
        response = "[main abc123] Fix login bug\n 1 file changed"
        self.assertEqual(bash_post_tool.parse_commit_message(response), "Fix login bug")


# ===========================================================================
# Bash Failure (PostToolUseFailure)
# ===========================================================================


def _make_bash_failure_input(
    command: str = "echo hi", error: str = "exit code 1", **overrides
) -> dict:
    """Build a canonical PostToolUseFailure Bash input dict."""
    data = {
        "session_id": "t",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": error,
        "is_interrupt": False,
        "agent_id": "main",
    }
    data.update(overrides)
    return data


class TestBashFailure(_HookTestCase):
    """Tests for bash_failure.py PostToolUseFailure handler."""

    def setUp(self):
        super().setUp()
        import bash_failure

        self.mod = bash_failure

    def test_xp_agent_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_type="xp-nav"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_interrupt_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="interrupted", is_interrupt=True
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_no_smm_dir_degrades(self):
        inp = _make_bash_failure_input(command="pytest", error="exit 1")
        self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        # No crash

    def test_non_test_command_ignored(self):
        inp = _make_bash_failure_input(command="ls -la", error="exit 2")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_pytest_failure_records_status_and_concern(self):
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertIn("non-zero status code 2", statuses[0]["content"])


class TestBashFailureSecurity(_HookTestCase):
    """Security tests for bash_failure.py."""

    def setUp(self):
        super().setUp()
        import bash_failure

        self.mod = bash_failure

    def test_path_traversal_agent_id_rejected(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_id="../../evil"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


# ===========================================================================
# hooks.json PostToolUse registration — Milestone 3.3
# ===========================================================================


class TestPostToolUseHooksConfig(unittest.TestCase):
    def test_hooks_json_has_post_tool_use(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("PostToolUse", data["hooks"])

    def test_post_tool_use_write_matcher(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Write|Edit|MultiEdit", matchers)

    def test_post_tool_use_bash_matcher(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Bash", matchers)

    def test_settings_has_commit_threshold(self):
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        with open(settings_path) as f:
            data = json.load(f)
        self.assertIn("commit_size_threshold", data)
        self.assertEqual(data["commit_size_threshold"], 10)


if __name__ == "__main__":
    unittest.main()
