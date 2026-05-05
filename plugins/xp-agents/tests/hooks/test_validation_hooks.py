#!/usr/bin/env python3
"""hooks.json registration tests for M5.4, gap fixes, and M6.5 migration.

Split from test_validation.py to keep both files under the 500-line target.
The earlier hooks.json tests (M3.4, M4, M5) and the prompt-files /
acceptance-criteria tests stay in test_validation.py; this module owns the
later milestone-specific hook registration assertions.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from _hooks_json import HooksJsonTestCase

# ===========================================================================
# hooks.json M5.4 registration tests
# ===========================================================================


class TestHooksJsonM54(HooksJsonTestCase):
    """Verify hooks.json has M5.4 hook registrations."""

    def test_stop_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_has_six_hooks(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        self.assertEqual(
            len(all_hooks),
            6,
            "Expected 6 Stop hooks (TDD + sprint + close-cycle + housekeeping"
            f" + warning + teammate), got {len(all_hooks)}",
        )
        commands = [h["command"] for h in all_hooks if "command" in h]
        self.assertTrue(any("sprint_stop_gate.py" in c for c in commands))
        self.assertTrue(any("close_cycle_stop_gate.py" in c for c in commands))
        self.assertTrue(any("housekeeping_stop_gate.py" in c for c in commands))
        self.assertTrue(any("session_end_warning.py" in c for c in commands))
        self.assertTrue(any("teammate_stop_gate.py" in c for c in commands))


# ===========================================================================
# hooks.json gap fixes — PostToolUseFailure + SessionStart clear
# ===========================================================================


class TestHooksJsonGapFixes(HooksJsonTestCase):
    """Verify hooks.json registrations for PostToolUseFailure and clear matcher."""

    def test_post_tool_use_failure_section_exists(self):
        self.assertIn(
            "PostToolUseFailure",
            self.data["hooks"],
            "PostToolUseFailure section missing from hooks.json",
        )

    def test_post_tool_use_failure_has_bash_matcher(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        matchers = [e.get("matcher") for e in entries]
        self.assertIn("Bash", matchers)

    def test_post_tool_use_failure_has_bash_failure_command(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("bash_failure.py" in h["command"] for h in commands),
            "bash_failure.py missing from PostToolUseFailure",
        )

    def test_post_tool_use_failure_has_ask_user_question_matcher(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        matchers = [e.get("matcher") for e in entries]
        self.assertIn(
            "AskUserQuestion",
            matchers,
            "AskUserQuestion missing from PostToolUseFailure",
        )

    def test_post_tool_use_failure_ask_user_has_question_answered(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        ask_entry = next(e for e in entries if e.get("matcher") == "AskUserQuestion")
        commands = [h["command"] for h in ask_entry.get("hooks", [])]
        self.assertTrue(
            any("question_answered.py" in c for c in commands),
            "question_answered.py missing from PostToolUseFailure",
        )

    def test_session_start_includes_clear_matcher(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        self.assertIsNotNone(entry, "SessionStart matcher should include 'clear'")


# ===========================================================================
# Milestone 6.5: Agent Hook → Plugin Subagent Migration
# ===========================================================================


class TestHooksJsonM65(HooksJsonTestCase):
    """Verify no agent hooks remain in hooks.json after M6.5 migration."""

    def test_no_agent_hooks_anywhere(self):
        """hooks.json should have zero type: agent entries."""
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertNotEqual(
                        hook.get("type"),
                        "agent",
                        f"Found agent hook in {event_name}: {hook}",
                    )

    def test_hooks_json_has_worktree_create(self):
        """WorktreeCreate hook must be registered."""
        self.assertIn("WorktreeCreate", self.data["hooks"])

    def test_worktree_create_command(self):
        """WorktreeCreate must reference worktree_create.py."""
        entry = self._find_default_entry("WorktreeCreate")
        assert entry is not None, "No default WorktreeCreate entry"
        cmds = [h["command"] for h in entry["hooks"]]
        self.assertTrue(any("worktree_create.py" in c for c in cmds))

    def test_only_command_and_prompt_types(self):
        """All hooks should be type: command or type: prompt."""
        valid_types = {"command", "prompt"}
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertIn(
                        hook.get("type"),
                        valid_types,
                        f"Invalid hook type in {event_name}: {hook.get('type')}",
                    )

    def test_no_prompt_hooks_remain(self):
        """All prompt hooks replaced by command hooks — none should remain."""
        prompt_hooks = []
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "prompt":
                        prompt_hooks.append((event_name, hook))
        self.assertEqual(len(prompt_hooks), 0, "No prompt hooks should remain")


if __name__ == "__main__":
    unittest.main()
