#!/usr/bin/env python3
"""Tests for pre_tool_write.py: conflict detection, TDD order, plan review gate."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import coordination
import pre_tool_write
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    _HookTestCase,
    _make_bash_input,
    _make_write_input,
    make_event,
)

# ===========================================================================
# pre_tool_write.py helper tests
# ===========================================================================


class TestIsTestFile(unittest.TestCase):
    def test_python_test_prefix(self):
        self.assertTrue(pre_tool_write.is_test_file("test_foo.py"))

    def test_python_test_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("foo_test.py"))

    def test_js_test(self):
        self.assertTrue(pre_tool_write.is_test_file("app.test.js"))

    def test_ts_spec(self):
        self.assertTrue(pre_tool_write.is_test_file("app.spec.ts"))

    def test_go_test(self):
        self.assertTrue(pre_tool_write.is_test_file("handler_test.go"))

    def test_java_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.java"))

    def test_ruby_spec(self):
        self.assertTrue(pre_tool_write.is_test_file("user_spec.rb"))

    def test_tests_directory(self):
        self.assertTrue(pre_tool_write.is_test_file("tests/conftest.py"))

    def test_dunder_tests_directory(self):
        self.assertTrue(pre_tool_write.is_test_file("__tests__/Button.tsx"))

    def test_impl_file(self):
        self.assertFalse(pre_tool_write.is_test_file("src/app.ts"))

    def test_python_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("models.py"))

    def test_swift_tests_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("JaroWinklerTests.swift"))

    def test_xcode_tests_directory(self):
        self.assertTrue(
            pre_tool_write.is_test_file("ContactForgeTests/JaroWinklerTests.swift")
        )

    def test_swift_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("ContactForge/JaroWinkler.swift"))

    def test_rust_test_suffix(self):
        self.assertTrue(pre_tool_write.is_test_file("handler_test.rs"))

    def test_rust_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("src/handler.rs"))

    def test_kotlin_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.kt"))

    def test_kotlin_tests(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTests.kt"))

    def test_csharp_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.cs"))

    def test_cpp_test(self):
        self.assertTrue(pre_tool_write.is_test_file("test_handler.cpp"))
        self.assertTrue(pre_tool_write.is_test_file("handler_test.cc"))

    def test_cpp_impl(self):
        self.assertFalse(pre_tool_write.is_test_file("handler.cpp"))

    def test_php_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.php"))

    def test_dart_test(self):
        self.assertTrue(pre_tool_write.is_test_file("widget_test.dart"))

    def test_elixir_test(self):
        self.assertTrue(pre_tool_write.is_test_file("user_test.exs"))

    def test_maven_test_dir(self):
        self.assertTrue(pre_tool_write.is_test_file("src/test/java/UserTest.java"))

    def test_spec_dir(self):
        self.assertTrue(pre_tool_write.is_test_file("spec/user_spec.rb"))

    def test_scala_test(self):
        self.assertTrue(pre_tool_write.is_test_file("UserTest.scala"))


class TestGetTargetFile(unittest.TestCase):
    def test_write_returns_file_path(self):
        self.assertEqual(
            _common.extract_file_path("Write", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_edit_returns_file_path(self):
        self.assertEqual(
            _common.extract_file_path("Edit", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_bash_returns_none(self):
        self.assertIsNone(_common.extract_file_path("Bash", {"command": "ls"}))

    def test_read_returns_none(self):
        self.assertIsNone(
            _common.extract_file_path("Read", {"file_path": "src/app.ts"})
        )

    def test_missing_file_path(self):
        self.assertIsNone(_common.extract_file_path("Write", {}))


class TestCheckWorkingOnOverlap(_HookTestCase):
    """Tests updated for coordination-file based overlap detection."""

    def test_no_overlap(self):
        coordination.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/a.ts", "/project"
        )
        self.assertIsNone(result)

    def test_overlap_detected(self):
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)
        self.assertIn("other", result)

    def test_self_overlap_ignored(self):
        coordination.update_coordination(self.smm_dir, "main", ["src/app.ts"])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_normalized_path_overlap(self):
        coordination.update_coordination(self.smm_dir, "other", ["./src/../src/app.ts"])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)

    def test_update_overwrites_previous(self):
        """Latest coordination update replaces previous working_on."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        coordination.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_empty_working_on_clears_overlap(self):
        """working_on=[] should clear the agent's file claim."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        coordination.update_coordination(self.smm_dir, "other", [])
        result = pre_tool_write.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)


class TestCheckTddOrder(_HookTestCase):
    def test_first_impl_no_nudge(self):
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Write"
        )
        self.assertIsNone(result)

    def test_second_impl_nudge(self):
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNotNone(result)
        self.assertIn("TDD", result)

    def test_test_file_clears_nudge(self):
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "tests/test_app.py", "Write"
        )
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNone(result)

    def test_non_write_tool_no_tracking(self):
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Read"
        )
        self.assertIsNone(result)

    def test_none_file_path(self):
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", None, "Write")
        self.assertIsNone(result)

    def test_markdown_no_tracking(self):
        """Non-code files (md, json, yaml) should not trigger TDD nudge."""
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "docs/README.md", "Write")
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "docs/DESIGN.md", "Write"
        )
        self.assertIsNone(result)

    def test_execution_plan_no_tracking(self):
        """execution_plan.json should not trigger TDD nudge."""
        pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "execution_plan.json", "Write"
        )
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "sprint.md", "Write"
        )
        self.assertIsNone(result)

    def test_code_after_markdown_still_nudges(self):
        """Markdown writes don't count, but code writes after them do."""
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "docs/README.md", "Write")
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.py", "Write")
        result = pre_tool_write.check_tdd_order(
            self.smm_dir, "main", "src/utils.py", "Write"
        )
        self.assertIsNotNone(result)
        self.assertIn("TDD", result)


class TestPreToolWriteRun(_HookTestCase):
    def test_xp_agent_skips(self):
        result = pre_tool_write.run(
            _make_write_input(agent_type="xp-housekeeping"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_write_no_delta_injection(self):
        """M5: Write tool no longer gets smm-delta injection."""
        events = [make_event("question", priority="\U0001f534", content="blocker?")]
        self._write_events(events)
        result = pre_tool_write.run(
            _make_write_input(tool_input={"file_path": "src/new.ts"}),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)

    def test_read_tool_no_injection(self):
        """Read tool input passed to pre_tool_write returns None."""
        events = [make_event("status", content="working")]
        self._write_events(events)
        result = pre_tool_write.run(
            {
                "session_id": "t",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_conflict_raises_blocked(self):
        coordination.update_coordination(self.smm_dir, "other-agent", ["src/app.ts"])
        with self.assertRaises(_common.BlockedError) as cm:
            pre_tool_write.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
        self.assertIn("other-agent", str(cm.exception))

    def test_conflict_appends_concern_event(self):
        """Conflict detection appends a high-severity concern to SMM."""
        coordination.update_coordination(self.smm_dir, "other-agent", ["src/app.ts"])
        with self.assertRaises(_common.BlockedError):
            pre_tool_write.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")
        self.assertIn("CONFLICT", concerns[0]["content"])

    def test_no_smm_dir_degrades_gracefully(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = pre_tool_write.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-debt-context", result)

    def test_bash_input_returns_none(self):
        """Bash input passed to pre_tool_write returns None."""
        events = [make_event("status", content="Working on API")]
        self._write_events(events)
        result = pre_tool_write.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestPreToolWriteNoDelta(_HookTestCase):
    """M5: Verify no delta/context injection for write tools."""

    def test_write_no_delta(self):
        """Write tool no longer gets delta."""
        events = [make_event("status", content="Working on app")]
        self._write_events(events)
        result = pre_tool_write.run(
            _make_write_input(tool_input={"file_path": "/tmp/src/new.ts"}),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)

    def test_read_tool_no_injection(self):
        """Read tool does not get SMM context injection."""
        events = [make_event("status", content="Working")]
        self._write_events(events)
        result = pre_tool_write.run(
            {
                "session_id": "t",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestPreToolWritePerformance(_HookTestCase):
    """AC (M3.2): Fast -- minimal overhead on every tool call."""

    def test_run_completes_within_budget(self):
        """100 invocations should complete well under 2 seconds."""
        import time

        events = [make_event("status", content=f"s{i}") for i in range(10)]
        self._write_events(events)

        input_data = _make_write_input(session_id="perf")

        start = time.monotonic()
        for _ in range(100):
            pre_tool_write.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 2.0, f"100 runs took {elapsed:.2f}s -- too slow")

    def test_xp_agent_skip_is_instant(self):
        """xp-agent bypass should be near-zero cost."""
        import time

        input_data = _make_write_input(session_id="perf", agent_type="xp-housekeeping")

        start = time.monotonic()
        for _ in range(1000):
            pre_tool_write.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0, f"1000 xp-agent skips took {elapsed:.2f}s")


class TestPreToolWritePlanReviewGate(_HookTestCase):
    """PreToolUse blocks writes when plan is unreviewed."""

    def test_unreviewed_plan_blocks_write(self):
        """Write with .plan-awaiting-review marker should block."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-review-plan", str(ctx.exception))

    def test_plan_file_write_allowed_with_marker(self):
        """Write to .claude/plans/ should be allowed even with marker."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan\n1. Do stuff",
            },
        )
        result = pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        # Should NOT raise — plan files are exempt
        if result:
            self.assertNotIn("xp-review-plan", result)

    def test_no_marker_no_block(self):
        """Write without marker should not block."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        # Should not raise — result is None or context string without plan review
        if result:
            self.assertNotIn("xp-review-plan", result)

    def test_marker_removed_no_block(self):
        """Write after marker removed should not block."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        marker.unlink()
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-review-plan", result)


class TestQuestionGate(_HookTestCase):
    """PreToolUse blocks writes when a blocking question is unanswered."""

    def test_question_gate_blocks_write(self):
        """Write with .question-gate should block."""
        gate = self.smm_dir / ".question-gate"
        gate.write_text("test-question-id")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("AskUserQuestion", str(ctx.exception))

    def test_no_question_gate_no_block(self):
        """Write without .question-gate should not block."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("AskUserQuestion", result)


class TestAcceptMarker(_HookTestCase):
    """pre_tool_write sets accept marker when in-progress stories exist."""

    def test_sets_accept_marker_when_in_progress_stories(self):
        """Write + in-progress stories → marker set."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_no_marker_when_no_sprint(self):
        """Write + no sprint → no marker."""
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_marker_when_no_in_progress(self):
        """Write + all ready stories → no marker."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_idempotent_marker_setting(self):
        """Marker already exists → no error, still exists."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_plan_file_does_not_set_marker(self):
        """Plan file writes should not trigger accept marker."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan",
            },
        )
        pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".accept").exists())


if __name__ == "__main__":
    unittest.main()
