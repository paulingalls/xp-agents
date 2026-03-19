#!/usr/bin/env python3
"""Tests for PreToolUse hook: pre_tool_use.py.

Split from the monolithic test_hooks.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import coordination
import pre_tool_use
import security
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _make_write_input,
    _override_settings,
    make_event,
)

# ===========================================================================
# pre_tool_use.py helper tests
# ===========================================================================


class TestIsTestFile(unittest.TestCase):
    def test_python_test_prefix(self):
        self.assertTrue(pre_tool_use.is_test_file("test_foo.py"))

    def test_python_test_suffix(self):
        self.assertTrue(pre_tool_use.is_test_file("foo_test.py"))

    def test_js_test(self):
        self.assertTrue(pre_tool_use.is_test_file("app.test.js"))

    def test_ts_spec(self):
        self.assertTrue(pre_tool_use.is_test_file("app.spec.ts"))

    def test_go_test(self):
        self.assertTrue(pre_tool_use.is_test_file("handler_test.go"))

    def test_java_test(self):
        self.assertTrue(pre_tool_use.is_test_file("UserTest.java"))

    def test_ruby_spec(self):
        self.assertTrue(pre_tool_use.is_test_file("user_spec.rb"))

    def test_tests_directory(self):
        self.assertTrue(pre_tool_use.is_test_file("tests/conftest.py"))

    def test_dunder_tests_directory(self):
        self.assertTrue(pre_tool_use.is_test_file("__tests__/Button.tsx"))

    def test_impl_file(self):
        self.assertFalse(pre_tool_use.is_test_file("src/app.ts"))

    def test_python_impl(self):
        self.assertFalse(pre_tool_use.is_test_file("models.py"))


class TestGetTargetFile(unittest.TestCase):
    def test_write_returns_file_path(self):
        self.assertEqual(
            pre_tool_use.get_target_file("Write", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_edit_returns_file_path(self):
        self.assertEqual(
            pre_tool_use.get_target_file("Edit", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_bash_returns_none(self):
        self.assertIsNone(pre_tool_use.get_target_file("Bash", {"command": "ls"}))

    def test_read_returns_none(self):
        self.assertIsNone(
            pre_tool_use.get_target_file("Read", {"file_path": "src/app.ts"})
        )

    def test_missing_file_path(self):
        self.assertIsNone(pre_tool_use.get_target_file("Write", {}))


class TestCheckWorkingOnOverlap(_HookTestCase):
    """Tests updated for coordination-file based overlap detection."""

    def test_no_overlap(self):
        coordination.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/a.ts", "/project"
        )
        self.assertIsNone(result)

    def test_overlap_detected(self):
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)
        self.assertIn("other", result)

    def test_self_overlap_ignored(self):
        coordination.update_coordination(self.smm_dir, "main", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_normalized_path_overlap(self):
        coordination.update_coordination(self.smm_dir, "other", ["./src/../src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)

    def test_update_overwrites_previous(self):
        """Latest coordination update replaces previous working_on."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        coordination.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_empty_working_on_clears_overlap(self):
        """working_on=[] should clear the agent's file claim."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        coordination.update_coordination(self.smm_dir, "other", [])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)


class TestCheckTddOrder(_HookTestCase):
    def test_first_impl_no_nudge(self):
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Write"
        )
        self.assertIsNone(result)

    def test_second_impl_nudge(self):
        # First write
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        # Second write
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNotNone(result)
        self.assertIn("TDD", result)

    def test_test_file_clears_nudge(self):
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "tests/test_app.py", "Write")
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNone(result)

    def test_non_write_tool_no_tracking(self):
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Read"
        )
        self.assertIsNone(result)

    def test_none_file_path(self):
        result = pre_tool_use.check_tdd_order(self.smm_dir, "main", None, "Write")
        self.assertIsNone(result)


class TestPreToolUseRun(_HookTestCase):
    def test_xp_agent_skips(self):
        result = pre_tool_use.run(
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_write_no_delta_injection(self):
        """M5: Write tool no longer gets smm-delta injection."""
        events = [make_event("question", priority="\U0001f534", content="blocker?")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/new.ts"}),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)

    def test_read_tool_no_injection(self):
        # Write a status event — Read tool should NOT get injection
        events = [make_event("status", content="working")]
        self._write_events(events)
        result = pre_tool_use.run(
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
            pre_tool_use.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
        self.assertIn("other-agent", str(cm.exception))

    def test_conflict_appends_concern_event(self):
        """Conflict detection appends a high-severity concern to SMM."""
        coordination.update_coordination(self.smm_dir, "other-agent", ["src/app.ts"])
        with self.assertRaises(_common.BlockedError):
            pre_tool_use.run(
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
        result = pre_tool_use.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )
        # Write tools still get navigator nudge even without SMM
        # but no SMM-dependent content (delta, debt, etc.)
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-debt-context", result)

    def test_bash_no_context_injection(self):
        """M5: Bash tool no longer gets smm-context injection."""
        events = [make_event("status", content="Working on API")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-delta", result)


# ===========================================================================
# pre_tool_use — Active Context, enforcement, debt injection (M5.3)
# ===========================================================================


class TestPreToolUseNoDelta(_HookTestCase):
    """M5: Verify no delta/context injection for any tool type."""

    def test_bash_no_context_injection(self):
        """Bash (non-commit) no longer gets Active Context."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api-style"),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-delta", result)

    def test_bash_commit_no_delta(self):
        """Bash with git commit no longer gets delta."""
        events = [make_event("decision", content="Use REST", topic="api-style")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)

    def test_write_no_delta(self):
        """Write tool no longer gets delta."""
        events = [make_event("status", content="Working on app")]
        self._write_events(events)
        result = pre_tool_use.run(
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
        result = pre_tool_use.run(
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


class TestPreToolUseEnforcement(_HookTestCase):
    def test_advisory_converts_block_to_warning(self):
        """Advisory mode converts BlockedError to warning in context."""
        coordination.update_coordination(
            self.smm_dir, "other-agent", ["/tmp/src/app.ts"]
        )
        with _override_settings({"enforcement": "advisory"}):
            result = pre_tool_use.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result)
            self.assertIn("CONFLICT", result)
            self.assertIn("advisory", result.lower())

    def test_strict_blocks(self):
        """Strict mode still raises BlockedError."""
        coordination.update_coordination(
            self.smm_dir, "other-agent", ["/tmp/src/app.ts"]
        )
        with self.assertRaises(_common.BlockedError):
            pre_tool_use.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )

    def test_advisory_indicator_in_context(self):
        """Advisory mode appends enforcement indicator."""
        events = [make_event("goal", content="Ship")]
        self._write_events(events)
        with _override_settings({"enforcement": "advisory"}):
            result = pre_tool_use.run(
                _make_bash_input(command="npm test"),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result)
            self.assertIn("[enforcement: advisory]", result)


class TestPreToolUseDebtInjection(_HookTestCase):
    def test_debt_included_for_write_tools(self):
        """Write tools get debt info for target file."""
        events = [
            make_event("debt", content="Legacy coupling", files=["/tmp/src/app.ts"]),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "/tmp/src/app.ts", "content": "x"}
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Legacy coupling", result)

    def test_no_debt_for_clean_file(self):
        """No debt injection section when file has no debt events."""
        events = [
            make_event("debt", content="Legacy coupling", files=["/tmp/src/other.ts"]),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "/tmp/src/app.ts", "content": "x"}
            ),
            smm_dir=self.smm_dir,
        )
        # Delta may include the debt event, but debt injection section should be absent
        if result:
            self.assertNotIn("smm-debt-context", result)


class TestPreToolUsePerformance(_HookTestCase):
    """AC (M3.2): Fast — minimal overhead on every tool call."""

    def test_run_completes_within_budget(self):
        """100 invocations should complete well under 2 seconds."""
        import time

        # Seed some events so delta reading has work to do
        events = [make_event("status", content=f"s{i}") for i in range(10)]
        self._write_events(events)

        input_data = {
            "session_id": "perf",
            "tool_name": "Read",
            "tool_input": {"file_path": "src/app.ts"},
            "agent_id": "perf-agent",
            "cwd": "/tmp",
        }

        start = time.monotonic()
        for _ in range(100):
            pre_tool_use.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        # 100 runs should complete in under 2 seconds on any reasonable machine
        self.assertLess(elapsed, 2.0, f"100 runs took {elapsed:.2f}s — too slow")

    def test_xp_agent_skip_is_instant(self):
        """xp-agent bypass should be near-zero cost."""
        import time

        input_data = _make_write_input(session_id="perf", agent_type="xp-navigator")

        start = time.monotonic()
        for _ in range(1000):
            pre_tool_use.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        # 1000 no-op runs should be well under 1 second
        self.assertLess(elapsed, 1.0, f"1000 xp-agent skips took {elapsed:.2f}s")


# ===========================================================================
# M6.5: Navigator nudge removed tests
# ===========================================================================


class TestPreToolUseNoNavigatorNudge(_HookTestCase):
    """Navigator nudge removed — concerns visible via SMM delta."""

    def test_write_no_navigator_nudge(self):
        """Write tool should not contain navigator nudge."""
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-navigator", result)

    def test_edit_no_navigator_nudge(self):
        """Edit tool should not contain navigator nudge."""
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "src/app.ts",
                    "old_string": "x",
                    "new_string": "y",
                },
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-navigator", result)

    def test_concerns_not_in_pretooluse(self):
        """M5: Concerns no longer injected via delta — delivered via prompt nugget."""
        self._write_events(
            [
                make_event("concern", content="Auth middleware is insecure"),
            ]
        )
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)


class TestPreToolUsePlanReviewGate(_HookTestCase):
    """PreToolUse nudges plan review for writes when plan is unreviewed."""

    def test_unreviewed_plan_nudges_review(self):
        """Write after plan_completed should nudge plan review."""
        self._write_events(
            [
                make_event(
                    "status",
                    content="plan_awaiting_review: Plan completed",
                    agent_id="plan-1",
                    working_on=[],
                ),
            ]
        )
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-plan-reviewer", result)

    def test_reviewed_plan_no_nudge(self):
        """Write after plan_reviewed should not nudge."""
        self._write_events(
            [
                make_event(
                    "status",
                    content="plan_awaiting_review: Plan completed",
                    agent_id="plan-1",
                    working_on=[],
                ),
                make_event(
                    "status",
                    content="plan_reviewed: Review complete",
                    agent_id="xp-plan-reviewer",
                    working_on=[],
                ),
            ]
        )
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("Run /xp-plan-reviewer", result)

    def test_no_plan_no_nudge(self):
        """Write without any plan should not nudge."""
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-plan-reviewer", result)

    def test_read_tool_no_plan_nudge(self):
        """Non-write tools should not get plan review nudge."""
        self._write_events(
            [
                make_event(
                    "status",
                    content="plan_awaiting_review: Plan completed",
                    agent_id="plan-1",
                ),
            ]
        )
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-plan-reviewer", result)


# ===========================================================================
# PreToolUse push gate — Milestone 5.5
# ===========================================================================


class TestPreToolUsePushGate(_HookTestCase):
    """Tests for git push security review gate in pre_tool_use.py."""

    def setUp(self):
        super().setUp()
        _common.load_enforcement_mode.cache_clear()

    def tearDown(self):
        _common.load_enforcement_mode.cache_clear()
        super().tearDown()

    def _push_input(self, command: str = "git push origin main", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_is_git_push_positive(self):
        """is_git_push detects various git push commands."""
        self.assertTrue(pre_tool_use.is_git_push("git push"))
        self.assertTrue(pre_tool_use.is_git_push("git push origin main"))
        self.assertTrue(pre_tool_use.is_git_push("git push --force"))

    def test_is_git_push_with_flags(self):
        """is_git_push detects git push with interleaved flags."""
        self.assertTrue(pre_tool_use.is_git_push("/usr/bin/git push"))
        self.assertTrue(pre_tool_use.is_git_push("git -c core.foo=bar push"))
        self.assertTrue(pre_tool_use.is_git_push("git -C /tmp push origin"))

    def test_is_git_push_negative(self):
        """is_git_push rejects non-push commands."""
        self.assertFalse(pre_tool_use.is_git_push("git commit -m 'test'"))
        self.assertFalse(pre_tool_use.is_git_push("git pull origin main"))
        self.assertFalse(pre_tool_use.is_git_push("echo push"))

    def test_push_blocked_without_tracker(self):
        """git push is blocked when no security tracker exists."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            self.assertIn("/security-review", str(ctx.exception))

    def test_push_passes_with_tracker(self):
        """git push passes when security tracker exists."""
        security.write_security_tracker(self.smm_dir, "abc1234")
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            # Should not raise BlockedError
            pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)

    def test_push_advisory_warns(self):
        """Advisory mode: git push warns instead of blocking."""
        with (
            _override_settings({"enforcement": "advisory"}),
            patch.object(security, "get_head_hash", return_value="abc1234"),
        ):
            result = pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            self.assertIsNotNone(result)
            self.assertIn("security", result.lower())

    def test_push_event_written_on_block(self):
        """Blocking a push writes security_review_requested event."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError):
                pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            events = _common.read_events_raw(self.smm_dir)
            sec_events = [
                e for e in events if e.get("type") == _common.SECURITY_REVIEW_REQUESTED
            ]
            self.assertEqual(len(sec_events), 1)
            self.assertIn("abc1234", sec_events[0]["content"])

    def test_push_no_smm_degrades(self):
        """git push with no SMM dir passes through (no crash)."""
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        pre_tool_use.run(self._push_input(), smm_dir=fake_dir)
        # No BlockedError — graceful degradation

    def test_push_no_hash_degrades(self):
        """git push with no HEAD hash passes through (no crash)."""
        with patch.object(security, "get_head_hash", return_value=None):
            pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            # No BlockedError — graceful degradation

    def test_push_xp_agent_skips(self):
        """xp- agents skip the push gate."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            pre_tool_use.run(
                self._push_input(agent_type="xp-navigator"),
                smm_dir=self.smm_dir,
            )
            # No BlockedError

    def test_non_push_bash_not_affected(self):
        """Non-push Bash commands don't trigger push gate."""
        inp = self._push_input(command="git status")
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            # Should not raise BlockedError
            pre_tool_use.run(inp, smm_dir=self.smm_dir)

    def test_non_bash_not_affected(self):
        """Non-Bash tools don't trigger push gate."""
        inp = {
            "session_id": "t",
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "git push"},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        # Should not raise BlockedError
        pre_tool_use.run(inp, smm_dir=self.smm_dir)


if __name__ == "__main__":
    unittest.main()
