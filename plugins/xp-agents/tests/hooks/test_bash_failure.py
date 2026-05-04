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
from conftest import (
    _HookTestCase,
    _make_bash_failure_input,
    _make_bash_input,
    _ProbeTestHelpers,
    make_event,
)
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS


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
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertIn("non-zero status code 2", statuses[0]["content"])

    def test_status_content_within_budget(self):
        """Status event from test failure must stay within 200-char budget."""
        from event_schema import CONTENT_BUDGETS

        inp = _make_bash_failure_input(
            command="pytest", error="x" * 500, framework="pytest"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertTrue(len(statuses) > 0, "No status event written")
        budget = CONTENT_BUDGETS["status"]
        self.assertLessEqual(
            len(statuses[0]["content"]),
            budget,
            f"status content {len(statuses[0]['content'])} exceeds {budget}",
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
        events = _common.read_events_raw(self.smm_dir)
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

        events = _common.read_events_raw(self.smm_dir)
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)

    def test_no_concerns_no_resolution(self):
        """No test concerns -> no resolution events."""
        bash_post_tool._resolve_test_concerns(self.smm_dir, "main")
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


class TestEventsReadDedup(_HookTestCase):
    """_handle_commit reads events.jsonl exactly once."""

    def test_read_events_raw_called_once(self):
        with (
            patch_commits(files=["src/app.py"], body="Fix"),
            patch(
                "bash_post_tool._common.read_events_raw",
                wraps=_common.read_events_raw,
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
            concerns.TEST_CONCERN_RE.search,
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
        events = _common.read_events_raw(self.smm_dir)
        import concerns

        with patch("concerns.read_events_raw") as mock_read:
            result = concerns.resolve_concerns(
                self.smm_dir,
                concerns.TEST_CONCERN_RE.search,
                "main",
                "Test concern resolved",
                events=events,
            )
        mock_read.assert_not_called()
        self.assertTrue(result)


class TestFindProbeCandidatesEventsKwarg(_ProbeTestHelpers, _HookTestCase):
    """resolves_probe.find_probe_candidates events= kwarg backward compat."""

    def test_events_none_reads_from_disk(self):
        """events=None delegates to commits.open_issues_matching_commit."""
        self._seed_auth_concern()
        import resolves_probe

        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["scripts/auth.py"], [], str(self.smm_dir)
        )
        self.assertEqual(len(result), 1)

    def test_events_provided_skips_disk_read(self):
        """events= provided passes through to commits, skipping disk read."""
        self._seed_auth_concern()
        events = _common.read_events_raw(self.smm_dir)
        import resolves_probe

        with patch("commits._common.read_events_raw") as mock_read:
            result = resolves_probe.find_probe_candidates(
                self.smm_dir,
                ["scripts/auth.py"],
                [],
                str(self.smm_dir),
                events=events,
            )
        mock_read.assert_not_called()
        self.assertEqual(len(result), 1)


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
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
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
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "bash_failed")
        self.assertNotIn("exit_code", metadata)


if __name__ == "__main__":
    unittest.main()
