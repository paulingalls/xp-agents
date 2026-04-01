#!/usr/bin/env python3
"""Tests for milestone checks, hooks.json validation, and plugin integrity.

Split from the monolithic test_hooks.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


# ===========================================================================
# hooks.json M3.4 registration tests
# ===========================================================================


class TestM34HooksConfig(unittest.TestCase):
    def setUp(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def test_hooks_json_has_user_prompt_submit(self):
        self.assertIn("UserPromptSubmit", self.data["hooks"])

    def test_user_prompt_submit_command(self):
        hooks = self.data["hooks"]["UserPromptSubmit"][0]["hooks"]
        cmds = [h["command"] for h in hooks]
        self.assertTrue(any("user_prompt_log.py" in c for c in cmds))

    def test_hooks_json_has_subagent_stop(self):
        self.assertIn("SubagentStop", self.data["hooks"])

    def test_subagent_stop_command(self):
        # Find the catch-all entry (no matcher) that has subagent_stop.py
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                hooks = entry["hooks"]
                cmds = [h["command"] for h in hooks if "command" in h]
                self.assertTrue(any("subagent_stop.py" in c for c in cmds))
                return
        self.fail("No catch-all SubagentStop entry found")

    def test_subagent_stop_has_timeout(self):
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                self.assertEqual(entry["hooks"][0]["timeout"], 5000)
                return
        self.fail("No catch-all SubagentStop entry found")


# ===========================================================================
# hooks.json test base class
# ===========================================================================


class _HooksJsonTestCase(unittest.TestCase):
    """Base class for hooks.json registration tests."""

    def setUp(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def _find_matcher_entry(self, hook_event: str, matcher: str) -> dict | None:
        """Find the entry with the given matcher in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if entry.get("matcher") == matcher:
                return entry
        return None

    def _find_default_entry(self, hook_event: str) -> dict | None:
        """Find an entry without a matcher (default) in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if "matcher" not in entry:
                return entry
        return None


# ===========================================================================
# hooks.json M4 registration tests
# ===========================================================================


class TestHooksJsonM4(_HooksJsonTestCase):
    """Verify hooks.json M4 registrations (agent hooks removed in M6.5)."""

    def test_pretooluse_write_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "Write|Edit|MultiEdit")
        self.assertIsNotNone(entry, "PreToolUse Write|Edit|MultiEdit entry missing")

    def test_pretooluse_bash_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "Bash")
        self.assertIsNotNone(entry, "PreToolUse Bash entry missing")

    def test_pretooluse_no_star_matcher(self):
        """Star matcher removed — split into Write|Edit|MultiEdit and Bash."""
        entry = self._find_matcher_entry("PreToolUse", "*")
        self.assertIsNone(entry, "PreToolUse * matcher should be removed")

    def test_posttooluse_no_agent_hooks(self):
        """Quality reviewer agent hook removed in M6.5."""
        entry = self._find_matcher_entry("PostToolUse", "Write|Edit|MultiEdit")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in PostToolUse")

    def test_subagentstop_no_plan_matcher(self):
        """Plan matcher entry removed in M6.5 (plan review via subagent now)."""
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        self.assertIsNone(entry, "SubagentStop Plan matcher entry should be removed")


# ===========================================================================
# Prompt file tests (Milestone 5)
# ===========================================================================


class TestPromptFilesM5(unittest.TestCase):
    """Verify prompt files state after tdd_check.md replaced by command hook."""

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

    def test_tdd_check_md_deleted(self):
        """tdd_check.md removed — replaced by tdd_stop_gate.py command hook."""
        self.assertFalse((self.prompts_dir / "tdd_check.md").exists())


# ===========================================================================
# M5.3 acceptance criteria — prompt content verification
# ===========================================================================


class TestM53AcceptanceCriteria(unittest.TestCase):
    """Verify M5.3 acceptance criteria are met.

    Prompt content checks updated in M6.5 to point to agents/ directory
    (agent hook prompts moved to plugin subagents).
    Testable behaviors verified in their respective test classes:
    - TestPreToolUseEnforcement (ACs 1-2)
    - TestLoadEnforcementMode (AC 3)
    - TestFindDebtForFile (AC 9)
    - TestPreToolUseDebtInjection (AC 10)
    - TestPreToolUseActiveContext (AC 15)
    """

    def setUp(self):
        self.agents_dir = Path(__file__).parent.parent.parent / "agents"

    # AC 4: first session asks for goals (now in skill)
    def test_goal_collection_skill(self):
        skill_dir = (
            Path(__file__).parent.parent.parent / "skills" / "xp-goal-collection"
        )
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Goal Collection", content)
        self.assertIn('--type "goal"', content)

    # AC 5: question triage distills intents (now in skill)
    def test_question_triage_intent_distillation(self):
        skill_dir = (
            Path(__file__).parent.parent.parent / "skills" / "xp-question-triage"
        )
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Intent Reconciliation", content)
        self.assertIn("customer_input", content)
        self.assertIn("--intent-status", content)

    # AC 7: delivered intents by event log activity
    def test_question_triage_delivery_by_events(self):
        skill_dir = (
            Path(__file__).parent.parent.parent / "skills" / "xp-question-triage"
        )
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("delivered", content)
        self.assertIn("recent events", content.lower())

    # AC 8: ambiguous keeps intent open
    def test_question_triage_err_toward_open(self):
        skill_dir = (
            Path(__file__).parent.parent.parent / "skills" / "xp-question-triage"
        )
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Err toward keeping intents open", content)

    # AC 12: retrospective escalates aging debt
    def test_retrospective_escalates_aging_debt(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Escalating aging debt", content)
        self.assertIn("high-priority", content)

    # AC 13: retrospective flags plugin health anomalies
    def test_retrospective_plugin_health(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Plugin Health", content)
        self.assertIn("session_stats", content)
        self.assertIn("concern", content)

    # AC 14: cross-session trends
    def test_retrospective_cross_session_trends(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("previous_retros", content)
        self.assertIn("cross-session", content.lower())


# ===========================================================================
# hooks.json M5 registration tests
# ===========================================================================


class TestHooksJsonM5(_HooksJsonTestCase):
    """Verify hooks.json has all M5 hook registrations."""

    # --- SessionStart: retrospective.py command ---

    def test_session_start_has_retrospective_command(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        commands = [h for h in entry["hooks"] if h.get("type") == "command"]
        self.assertTrue(
            any("retrospective.py" in h["command"] for h in commands),
            "retrospective.py command hook missing from SessionStart",
        )

    # --- SessionStart: agent hooks removed in M6.5 ---

    def test_session_start_no_agent_hooks(self):
        """Retro analyst and customer proxy agent hooks removed in M6.5."""
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in SessionStart")

    # --- SubagentStop: agent hooks removed in M6.5 ---

    def test_subagentstop_no_agent_hooks(self):
        """Subagent reviewer agent hook removed in M6.5."""
        for entry in self.data["hooks"]["SubagentStop"]:
            agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
            self.assertEqual(
                len(agents), 0, "No agent hooks should remain in SubagentStop"
            )

    # --- Stop: tdd_stop_gate command hook ---

    def test_stop_hook_exists(self):
        self.assertIn("Stop", self.data["hooks"], "Stop hook section missing")

    def test_stop_hook_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_hook_no_prompt_hooks(self):
        """Prompt hooks replaced by command hooks — none should remain."""
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        prompts = [h for h in all_hooks if h.get("type") == "prompt"]
        self.assertEqual(len(prompts), 0, "No prompt hooks should remain in Stop")


# ===========================================================================
# hooks.json M5.4 registration tests
# ===========================================================================


class TestHooksJsonM54(_HooksJsonTestCase):
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

    def test_stop_has_one_hook(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        self.assertEqual(
            len(all_hooks), 1, f"Expected 1 Stop hook (TDD only), got {len(all_hooks)}"
        )


# ===========================================================================
# hooks.json gap fixes — PostToolUseFailure + SessionStart clear
# ===========================================================================


class TestHooksJsonGapFixes(_HooksJsonTestCase):
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

    def test_session_start_includes_clear_matcher(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        self.assertIsNotNone(entry, "SessionStart matcher should include 'clear'")


# ===========================================================================
# Milestone 6.5: Agent Hook → Plugin Subagent Migration
# ===========================================================================


class TestHooksJsonM65(_HooksJsonTestCase):
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
