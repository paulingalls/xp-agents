#!/usr/bin/env python3
"""Tests for pre_tool_write.py: conflict detection, TDD order, cost invariants."""

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
import pre_tool_write
import read_delta
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _make_write_input,
    make_event,
)
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_QUESTION, EVENT_TYPE_STATUS

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

    def test_ts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("foo_test.ts"))

    def test_tsx_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("Button_test.tsx"))

    def test_js_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("util_test.js"))

    def test_jsx_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("Card_test.jsx"))

    def test_mts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("api_test.mts"))

    def test_cts_underscore_test(self):
        self.assertTrue(pre_tool_write.is_test_file("legacy_test.cts"))

    def test_ts_impl_with_underscore_not_test(self):
        # Underscore in the middle (not preceding "_test.") shouldn't fire.
        self.assertFalse(pre_tool_write.is_test_file("user_service.ts"))

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

    def test_multi_edit_returns_file_path(self):
        self.assertEqual(
            _common.extract_file_path("MultiEdit", {"file_path": "src/app.ts"}),
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
        result = self._assert_not_none(result)
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
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.ts")
        self.assertIsNone(result)

    def test_second_impl_nudge(self):
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.ts")
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/utils.ts")
        result = self._assert_not_none(result)
        self.assertIn("TDD", result)

    def test_test_file_clears_nudge(self):
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.ts")
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "tests/test_app.py")
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/utils.ts")
        self.assertIsNone(result)

    def test_none_file_path(self):
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", None)
        self.assertIsNone(result)

    def test_markdown_no_tracking(self):
        """Non-code files should not trigger TDD nudge."""
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "docs/README.md")
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "docs/DESIGN.md")
        self.assertIsNone(result)

    def test_execution_plan_no_tracking(self):
        """execution_plan.json should not trigger TDD nudge."""
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "execution_plan.json")
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "sprint.json")
        self.assertIsNone(result)

    def test_code_after_markdown_still_nudges(self):
        """Markdown writes don't count, but code writes after them do."""
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "docs/README.md")
        pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/app.py")
        result = pre_tool_write.check_tdd_order(self.smm_dir, "main", "src/utils.py")
        result = self._assert_not_none(result)
        self.assertIn("TDD", result)


class TestPreToolWriteRun(_HookTestCase):
    def test_xp_agent_skips(self):
        result = pre_tool_write.run(
            _make_write_input(agent_type="xp-housekeeper"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_write_no_delta_injection(self):
        """M5: Write tool no longer gets smm-delta injection."""
        events = [
            make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="blocker?")
        ]
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
        events = [make_event(EVENT_TYPE_STATUS, content="working")]
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
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
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
        events = [make_event(EVENT_TYPE_STATUS, content="Working on API")]
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
        events = [make_event(EVENT_TYPE_STATUS, content="Working on app")]
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
        events = [make_event(EVENT_TYPE_STATUS, content="Working")]
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


class TestPreToolWriteCostInvariants(_HookTestCase):
    """The hook's cost must not scale with history, and xp-* must cost nothing.

    Both were guarded by wall-clock budgets (100 runs < 2s; 1000 skips < 1s),
    which measured the machine: on a loaded box they go red on contention alone,
    on a fast one they pass no matter how much work run() does. Assert the
    structural invariants they stood in for instead -- WHAT run() touches -- and
    they hold on any machine at any load.
    """

    def _names_read_during(self, action) -> set[str]:
        """Filenames read by `action`, captured at the one chokepoint.

        Every events.jsonl read funnels through _append_impl.read_with_lock,
        which reads via path.read_text (_append_impl.py:184) -- so patching
        Path.read_text and capturing `self` sees any event-log scan, including
        read_delta's byte-offset path.

        The assertion and its positive control BOTH go through this one helper:
        a control that re-implements the spy only proves that some spy like it
        would work, not that the spy actually guarding run() does.
        """
        seen: list[Path] = []
        real = Path.read_text

        def spy(self, *args, **kwargs):
            seen.append(self)
            return real(self, *args, **kwargs)

        with patch.object(Path, "read_text", spy):
            action()
        return {p.name for p in seen}

    def test_run_never_scans_the_event_log(self):
        """run()'s cost is independent of history: it never reads events.jsonl.

        Every check is deliberately file-based/O(1) -- .coordination.json, marker
        files, sprint.json. A regression that scans the event log per tool call
        makes every Write pay for the whole project's history.
        """
        self._write_events(
            [make_event(EVENT_TYPE_STATUS, content=f"s{i}") for i in range(500)]
        )
        input_data = _make_write_input(session_id="perf")

        read = self._names_read_during(
            lambda: pre_tool_write.run(input_data, smm_dir=self.smm_dir)
        )

        self.assertNotIn(
            "events.jsonl",
            read,
            "run() scanned the event log -- its cost now grows with history",
        )

    def test_the_spy_sees_an_event_log_read(self):
        """Positive control for the assertion above (decision 308dd829d2a4).

        A code path that DOES read events.jsonl must show up in the SAME spy --
        hence the shared helper. Without this, a spy patched onto the wrong
        chokepoint sees nothing, and 'run() never reads the event log' passes
        forever while watching nothing.
        """
        self._write_events(
            [make_event(EVENT_TYPE_STATUS, content=f"s{i}") for i in range(10)]
        )

        read = self._names_read_during(
            lambda: read_delta.read_delta(self.smm_dir, "control")
        )

        self.assertIn(
            "events.jsonl",
            read,
            "the spy is not wired to the chokepoint -- it cannot see an event-log "
            "read even when one demonstrably happens",
        )

    def test_xp_agent_skip_touches_nothing(self):
        """The xp-* early return fires BEFORE any I/O.

        `if _common.is_xp_agent(input_data): return None` is the first statement
        in run(); everything after it (smm_dir validation, the coordination read,
        marker stats, the sprint read) must be unreached. A regression that moves
        the return below any of them makes every xp-* subagent pay the full gate
        cost on every write.
        """
        input_data = _make_write_input(session_id="perf", agent_type="xp-housekeeper")

        with (
            patch.object(coordination, "read_coordination") as coord,
            patch.object(pre_tool_write.markers, "marker_exists") as marker,
            patch.object(pre_tool_write.sprint_state, "read_sprint_content") as sprint,
        ):
            result = pre_tool_write.run(input_data, smm_dir=self.smm_dir)

        self.assertIsNone(result)
        coord.assert_not_called()
        marker.assert_not_called()
        sprint.assert_not_called()

    def test_a_non_xp_agent_does_reach_those_collaborators(self):
        """Positive control for the assertion above (decision 308dd829d2a4).

        ALL THREE collaborators, patched the same way, MUST be called for a normal
        agent -- otherwise 'never called' is vacuous: a patch target that run() no
        longer calls (renamed, inlined, routed through another module) would make
        the assertion above pass while asserting nothing at all. Every mock the
        skip test asserts unreached is asserted REACHED here; leave none out.

        marker_exists returns False rather than a bare MagicMock: a MagicMock is
        truthy, which would trip the plan-review gate and raise BlockedError.
        """
        with (
            patch.object(coordination, "read_coordination", return_value={}) as coord,
            patch.object(
                pre_tool_write.markers, "marker_exists", return_value=False
            ) as marker,
            patch.object(
                pre_tool_write.sprint_state, "read_sprint_content", return_value=None
            ) as sprint,
        ):
            pre_tool_write.run(_make_write_input(session_id="perf"), self.smm_dir)

        coord.assert_called()
        marker.assert_called()
        sprint.assert_called()


if __name__ == "__main__":
    unittest.main()
