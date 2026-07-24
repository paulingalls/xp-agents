#!/usr/bin/env python3
"""Tests for bash_failure.py, test concern resolution, events kwarg compat,
and events-read dedup.

Split from test_bash.py.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import bash_post_tool
from _commit_helpers import patch_commits
from concerns import TEST_CONCERN_RE, TEST_FAILURES_PREFIX
from conftest import (
    _HookTestCase,
    _make_bash_failure_input,
    _make_bash_input,
    make_event,
)
from event_helpers import events_of_type
from event_metadata import CONCERN_ACTION_TRANSIENT_TEST
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    get_required_budget,
)

_WATERMARK_ID = "test-bash-failure"


class TestBashFailure(_HookTestCase):
    """Tests for bash_failure.py PostToolUseFailure handler."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_xp_agent_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_type="xp-nav"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)

    def test_interrupt_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="interrupted", is_interrupt=True
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)

    def test_no_smm_dir_degrades(self):
        inp = _make_bash_failure_input(command="pytest", error="exit 1")
        self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))

    def test_non_test_command_ignored(self):
        inp = _make_bash_failure_input(command="ls -la", error="exit 2")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)

    def test_pytest_failure_records_status_and_concern(self):
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_concern_carries_the_transient_marker(self):
        """The scoped close-gate count excludes this class by PROVENANCE.

        `smm_count._is_transient_test_concern` keys on this marker and has no
        content fallback, so if this producer stops stamping it, a concurrent
        teammate's red-step concern silently starts false-aborting a sibling's
        clean close again (concern f995656dba80) — with every count-concerns
        test still green, because those construct their own fixtures. This is
        the pin that keeps the producer and the consumer in agreement.
        """
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertEqual(
            concerns[0].get("metadata", {}).get("action"),
            CONCERN_ACTION_TRANSIENT_TEST,
        )

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertIn("non-zero status code 2", statuses[0]["content"])

    def test_status_content_within_budget(self):
        """Status event from test failure must stay within 200-char budget."""
        from event_schema import get_required_budget

        inp = _make_bash_failure_input(
            command="pytest", error="x" * 500, framework="pytest"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertTrue(len(statuses) > 0, "No status event written")
        budget = get_required_budget("status")
        self.assertLessEqual(
            len(statuses[0]["content"]),
            budget,
            f"status content {len(statuses[0]['content'])} exceeds {budget}",
        )


class TestFailureAttribution(_HookTestCase):
    """The writer only claims a test failure it can actually observe.

    `bash_failure` fires on ANY non-zero Bash exit, and `is_test_run` matches a
    runner name anywhere in the command — so before this, a compound command
    that short-circuited before the runner filed a high-severity test-failure
    concern for a run that never happened, and the TDD gate read it as
    "tests are failing".
    """

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def _run(self, command: str, error: str) -> list[dict]:
        self.mod.run(
            _make_bash_failure_input(command=command, error=error, exit_code=1),
            smm_dir=self.smm_dir,
        )
        return _common.read_events_locked(self.smm_dir, _WATERMARK_ID)

    def test_ambiguous_compound_writes_status_not_concern(self):
        """The load-bearing assertion, and the original repro: the validator
        failed, pytest never ran. Record that the command failed — but make NO
        test claim, so the gate does not block on a run we never observed.

        A status, not a concern: an unresolvable concern would gate the session
        forever and inflate pending_concerns.
        """
        events = self._run(
            "python3 plan_cli.py validate && python3 -m pytest tests/",
            "Exit code 1\nValidation errors:\n  - design_details 517/500 OVER",
        )
        self.assertEqual(events_of_type(events, EVENT_TYPE_CONCERN), [])
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1)
        self.assertNotRegex(statuses[0]["content"], TEST_CONCERN_RE)
        self.assertEqual(statuses[0]["metadata"]["action"], "bash_failed")

    def test_grep_for_runner_name_writes_status_not_concern(self):
        """`grep -rn pytest src/` exits 1 on no-match and is NOT compound —
        investigating this bug by grepping for the word reproduces it."""
        events = self._run("grep -rn pytest plugins/", "Exit code 1")
        self.assertEqual(events_of_type(events, EVENT_TYPE_CONCERN), [])
        self.assertEqual(len(events_of_type(events, EVENT_TYPE_STATUS)), 1)

    def test_attributed_failure_still_writes_concern(self):
        """Anti-disarm control. A bare failing runner has no ambiguity: the exit
        code IS the runner's, counts or no counts (segfault, collection error).
        """
        events = self._run("pytest tests/", "Exit code 1\nImportError: no module")
        concern_events = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concern_events), 1)
        self.assertEqual(concern_events[0]["severity"], "high")
        self.assertRegex(concern_events[0]["content"], TEST_CONCERN_RE)

    def test_corroborated_compound_reports_the_counts_it_observed(self):
        """A compound command whose payload carries real counts is no longer
        ambiguous — the concern is written, and it reports what was observed
        rather than a bare exit code."""
        events = self._run(
            "cd app && npx jest",
            "Exit code 1\nTests:  2 failed, 3 passed, 5 total",
        )
        concern_events = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concern_events), 1)
        self.assertIn(TEST_FAILURES_PREFIX, concern_events[0]["content"])
        self.assertIn("2 failed", concern_events[0]["content"])

    def test_first_line_skips_exit_code_line(self):
        """`error` is "Exit code N\\n<output>", so taking line 1 made every live
        concern read "Test command failed (pytest): Exit code 1" — worthless."""
        events = self._run("pytest tests/", "Exit code 1\nImportError: no module foo")
        content = events_of_type(events, EVENT_TYPE_CONCERN)[0]["content"]
        self.assertIn("ImportError: no module foo", content)
        self.assertNotIn("Exit code 1", content)

    def test_long_first_line_still_lands_the_concern(self):
        """Anti-disarm control, budget edge. `append_safe` SILENTLY DROPS an
        event that busts its content budget, so an unbounded detail line loses
        the concern entirely — the gate goes quiet on a real failing run, the
        worst direction. Line 1 used to be the harness's short "Exit code N",
        which hid this; the detail line now carries real runner output, which
        has no length bound (a one-line stack trace, a long assert repr).
        """
        events = self._run(
            "pytest tests/",
            "Exit code 1\nE   AssertionError: assert " + "x" * 500,
        )
        concern_events = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concern_events), 1)
        self.assertRegex(concern_events[0]["content"], TEST_CONCERN_RE)
        self.assertLessEqual(
            len(concern_events[0]["content"]),
            get_required_budget(_common.CONCERN),
        )


class TestBashFailureSecurity(_HookTestCase):
    """Security tests for bash_failure.py."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_path_traversal_agent_id_rejected(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_id="../../evil"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)


class TestResolveTestConcerns(_HookTestCase):
    """Tests for bash_post_tool._resolve_test_concerns."""

    def test_resolves_test_concern(self):
        """Test concerns are resolved when tests pass."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 3 failed",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)

        bash_post_tool._resolve_test_concerns(self.smm_dir, "main")

        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)

    def test_no_concerns_no_resolution(self):
        """No test concerns -> no resolution events."""
        bash_post_tool._resolve_test_concerns(self.smm_dir, "main")
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)


class TestEventsReadDedup(_HookTestCase):
    """_handle_commit reads events.jsonl exactly once."""

    def test_events_read_once(self):
        """Dedup: load_events_with_resolutions reads events.jsonl exactly once."""
        import read_delta

        with (
            patch_commits(files=["src/app.py"], body="Fix"),
            patch(
                "read_delta.read_delta_full",
                wraps=read_delta.read_delta_full,
            ) as spy,
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix'",
                    stdout="[main abc123] Fix\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertEqual(spy.call_count, 1)


class TestResolvesConcernsEventsKwarg(_HookTestCase):
    """concerns.resolve_concerns events= kwarg backward compatibility."""

    def test_events_none_reads_from_disk(self):
        """events=None (default) reads from disk."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 3 failed",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)
        import concerns

        result = concerns.resolve_concerns(
            self.smm_dir,
            TEST_CONCERN_RE.search,
            "main",
            "Test concern resolved",
        )
        self.assertTrue(result)

    def test_events_provided_skips_disk_read(self):
        """events= provided uses given events, no disk read."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 3 failed",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        import concerns

        with patch("concerns._common.read_events_locked") as mock_read:
            result = concerns.resolve_concerns(
                self.smm_dir,
                TEST_CONCERN_RE.search,
                "main",
                "Test concern resolved",
                events=events,
            )
        mock_read.assert_not_called()
        self.assertTrue(result)


class TestM2BashFailedAction(_HookTestCase):
    """sprint-042 M2: bash_failure status carries metadata.action=bash_failed
    + metadata.exit_code when the hook input provides one."""

    def test_status_carries_bash_failed_action(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 1",
            exit_code=1,
        )
        bash_failure.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1)
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "bash_failed")
        self.assertEqual(metadata.get("exit_code"), 1)

    def test_exit_code_omitted_when_input_lacks_it(self):
        """When the hook input does not provide exit_code, metadata still
        carries the action discriminator without inventing a fake code."""
        inp = _make_bash_failure_input(command="pytest", error="Command failed")
        # Drop exit_code if any default added it (none in _make_bash_failure_input).
        inp.pop("exit_code", None)
        bash_failure.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "bash_failed")
        self.assertNotIn("exit_code", metadata)


if __name__ == "__main__":
    unittest.main()
