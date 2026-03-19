#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: push security gate, file-modification heuristic."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import security
from conftest import (
    _HookTestCase,
    _make_bash_input,
    make_event,
)


class TestPreToolBashNoDelta(_HookTestCase):
    """M5: Verify no delta/context injection for bash tools."""

    def test_bash_no_context_injection(self):
        """Bash (non-commit) no longer gets Active Context."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api-style"),
        ]
        self._write_events(events)
        result = pre_tool_bash.run(
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
        result = pre_tool_bash.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("smm-delta", result)
            self.assertNotIn("smm-context", result)


class TestPreToolBashPushGate(_HookTestCase):
    """Tests for git push security review gate in pre_tool_bash.py."""

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
        self.assertTrue(pre_tool_bash.is_git_push("git push"))
        self.assertTrue(pre_tool_bash.is_git_push("git push origin main"))
        self.assertTrue(pre_tool_bash.is_git_push("git push --force"))

    def test_is_git_push_with_flags(self):
        """is_git_push detects git push with interleaved flags."""
        self.assertTrue(pre_tool_bash.is_git_push("/usr/bin/git push"))
        self.assertTrue(pre_tool_bash.is_git_push("git -c core.foo=bar push"))
        self.assertTrue(pre_tool_bash.is_git_push("git -C /tmp push origin"))

    def test_is_git_push_negative(self):
        """is_git_push rejects non-push commands."""
        self.assertFalse(pre_tool_bash.is_git_push("git commit -m 'test'"))
        self.assertFalse(pre_tool_bash.is_git_push("git pull origin main"))
        self.assertFalse(pre_tool_bash.is_git_push("echo push"))

    def test_push_blocked_without_tracker(self):
        """git push is blocked when no security tracker exists."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(self._push_input(), smm_dir=self.smm_dir)
            self.assertIn("/security-review", str(ctx.exception))

    def test_push_passes_with_tracker(self):
        """git push passes when security tracker exists."""
        security.write_security_tracker(self.smm_dir, "abc1234")
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            pre_tool_bash.run(self._push_input(), smm_dir=self.smm_dir)

    def test_push_event_written_on_block(self):
        """Blocking a push writes security_review_requested event."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError):
                pre_tool_bash.run(self._push_input(), smm_dir=self.smm_dir)
            events = _common.read_events_raw(self.smm_dir)
            sec_events = [
                e for e in events if e.get("type") == _common.SECURITY_REVIEW_REQUESTED
            ]
            self.assertEqual(len(sec_events), 1)
            self.assertIn("abc1234", sec_events[0]["content"])

    def test_push_no_smm_degrades(self):
        """git push with no SMM dir passes through (no crash)."""
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        pre_tool_bash.run(self._push_input(), smm_dir=fake_dir)

    def test_push_no_hash_degrades(self):
        """git push with no HEAD hash passes through (no crash)."""
        with patch.object(security, "get_head_hash", return_value=None):
            pre_tool_bash.run(self._push_input(), smm_dir=self.smm_dir)

    def test_push_xp_agent_skips(self):
        """xp- agents skip the push gate."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            pre_tool_bash.run(
                self._push_input(agent_type="xp-navigator"),
                smm_dir=self.smm_dir,
            )

    def test_non_push_bash_not_affected(self):
        """Non-push Bash commands don't trigger push gate."""
        inp = self._push_input(command="git status")
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            pre_tool_bash.run(inp, smm_dir=self.smm_dir)


if __name__ == "__main__":
    unittest.main()
