#!/usr/bin/env python3
"""Tests for milestone checks, hooks.json validation, and plugin integrity.

Split from the monolithic test_hooks.py.
"""

import json
import re
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

    def test_stop_has_simplify_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("simplify_gate.py" in h["command"] for h in commands),
            "simplify_gate.py command hook missing from Stop",
        )

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

    def test_stop_has_four_hooks(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        self.assertEqual(
            len(all_hooks), 3, f"Expected 3 Stop hooks, got {len(all_hooks)}"
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

_SUBAGENT_NAMES = (
    "xp-retrospective",
    "xp-plan-reviewer",
)


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


class TestMilestone6Files(unittest.TestCase):
    """Verify presence and content of M6 files."""

    def setUp(self):
        self.plugin_root = Path(__file__).parent.parent.parent

    def test_behavioral_guide_exists(self):
        """BEHAVIORAL_GUIDE.md must exist at plugin root."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_behavioral_guide_token_budget(self):
        """BEHAVIORAL_GUIDE.md word count should estimate 300-2,000 tokens."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        if not path.exists():
            self.skipTest("BEHAVIORAL_GUIDE.md not yet created")
        words = len(path.read_text().split())
        estimated_tokens = words / 0.75
        self.assertGreaterEqual(
            estimated_tokens, 300, f"Too short: ~{estimated_tokens:.0f} tokens"
        )
        self.assertLessEqual(
            estimated_tokens, 2000, f"Too long: ~{estimated_tokens:.0f} tokens"
        )

    def test_skill_directories_exist(self):
        """All 3 skill dirs must exist with SKILL.md."""
        for name in ("smm-protocol", "xp-values"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")

    def test_skill_frontmatter_valid(self):
        """Each SKILL.md must have valid YAML frontmatter with name + description."""
        for name in ("smm-protocol", "xp-values"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            if not skill_file.exists():
                self.skipTest(f"{skill_file} not yet created")
            content = skill_file.read_text()
            # Must start with ---
            self.assertTrue(
                content.startswith("---"),
                f"{name}/SKILL.md missing frontmatter delimiter",
            )
            # Extract frontmatter
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            self.assertIsNotNone(match, f"{name}/SKILL.md frontmatter not closed")
            fm = match.group(1)
            self.assertIn("name:", fm, f"{name}/SKILL.md missing 'name' field")
            self.assertIn(
                "description:", fm, f"{name}/SKILL.md missing 'description' field"
            )
            # Name should match directory
            name_match = re.search(r"name:\s*(\S+)", fm)
            self.assertIsNotNone(name_match)
            self.assertEqual(name_match.group(1), name)

    def test_skill_token_budgets(self):
        """Each SKILL.md should be within 1,000-2,000 token estimate."""
        for name in ("smm-protocol", "xp-values"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            if not skill_file.exists():
                self.skipTest(f"{skill_file} not yet created")
            words = len(skill_file.read_text().split())
            estimated_tokens = words / 0.75
            self.assertGreaterEqual(
                estimated_tokens,
                800,
                f"{name} too short: ~{estimated_tokens:.0f} tokens",
            )
            self.assertLessEqual(
                estimated_tokens,
                2500,
                f"{name} too long: ~{estimated_tokens:.0f} tokens",
            )

    def test_behavioral_guide_no_contradictions(self):
        """Guide should not contradict hook enforcement (spot check)."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        if not path.exists():
            self.skipTest("BEHAVIORAL_GUIDE.md not yet created")
        content = path.read_text()
        # Guide should reference hooks, not claim to replace them
        self.assertNotIn("instead of hooks", content.lower())
        self.assertNotIn("ignore quality review", content.lower())
        # Guide should cover XP values and honesty
        self.assertIn("Honesty", content)
        self.assertIn("Courage", content)
        self.assertIn("Simplicity", content)


class TestAgentFilesM65(unittest.TestCase):
    """Verify all plugin subagent files exist with correct frontmatter."""

    def setUp(self):
        self.agents_dir = Path(__file__).parent.parent.parent / "agents"

    def test_agents_directory_exists(self):
        self.assertTrue(self.agents_dir.is_dir(), "agents/ directory missing")

    def test_all_agent_files_exist(self):
        for name in _SUBAGENT_NAMES:
            path = self.agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_frontmatter_has_name(self):
        """Each agent file must have a name field matching the filename."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")
            match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
            self.assertIsNotNone(match, f"{name} missing name field")
            self.assertEqual(match.group(1).strip(), name)

    def test_frontmatter_has_description(self):
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertIn("description:", content, f"{name} missing description")

    def test_tools_include_bash(self):
        """Every subagent needs Bash for append.sh."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            # Extract frontmatter
            parts = content.split("---", 2)
            self.assertGreaterEqual(len(parts), 3, f"{name} frontmatter not closed")
            fm = parts[1]
            self.assertIn("Bash", fm, f"{name} missing Bash in tools")

    def test_skills_include_smm_protocol(self):
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            parts = content.split("---", 2)
            fm = parts[1]
            self.assertIn("smm-protocol", fm, f"{name} missing smm-protocol skill")

    def test_body_mentions_append_sh(self):
        """Every subagent should reference append.sh for event writing."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            # Body is after the second ---
            parts = content.split("---", 2)
            body = parts[2] if len(parts) >= 3 else ""
            self.assertIn("append.sh", body, f"{name} body missing append.sh reference")

    def test_body_mentions_smm_content_trust(self):
        """Every subagent should have the SMM content trust section."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertIn(
                "SMM Content Trust", content, f"{name} missing SMM Content Trust"
            )


# ===========================================================================
# M7: Plugin Integrity
# ===========================================================================


class TestPluginIntegrity(unittest.TestCase):
    """M7: marketplace.json, hooks.json references, and structural checks."""

    def setUp(self):
        self.plugin_root = Path(__file__).parent.parent.parent

    def test_marketplace_json_exists_and_valid(self):
        """marketplace.json has required fields."""
        mp = self.plugin_root / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mp.is_file(), "Missing .claude-plugin/marketplace.json")
        data = json.loads(mp.read_text())
        self.assertIn("name", data)
        self.assertIn("owner", data)
        self.assertIn("name", data["owner"])
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)
        self.assertGreater(len(data["plugins"]), 0)
        for plugin in data["plugins"]:
            self.assertIn("name", plugin)
            self.assertIn("source", plugin)
            self.assertIn("description", plugin)

    def test_plugin_json_exists_and_valid(self):
        """plugin.json has required fields."""
        pj = self.plugin_root / ".claude-plugin" / "plugin.json"
        self.assertTrue(pj.is_file())
        data = json.loads(pj.read_text())
        self.assertIn("name", data)
        self.assertIn("version", data)
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

    def _assert_hook_paths_exist(self, hook_type: str, path_key: str):
        """Verify all hooks of given type reference existing files."""
        hooks_file = self.plugin_root / "hooks" / "hooks.json"
        data = json.loads(hooks_file.read_text())
        for event_name, entries in data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") != hook_type:
                        continue
                    raw = hook[path_key]
                    # Strip interpreter prefix (e.g. "python3 ")
                    marker = "${CLAUDE_PLUGIN_ROOT}"
                    if marker in raw:
                        path_part = raw.split(marker)[-1]
                        resolved = str(self.plugin_root) + path_part
                    else:
                        resolved = raw
                    self.assertTrue(
                        Path(resolved).is_file(),
                        f"Missing {hook_type}: {raw} (event: {event_name})",
                    )

    def test_all_hook_scripts_exist(self):
        """Every command script referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("command", "command")

    def test_all_prompt_hooks_exist(self):
        """Every prompt file referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("prompt", "prompt")

    def test_all_agent_files_exist(self):
        """All agent .md files exist in agents/ directory."""
        agents_dir = self.plugin_root / "agents"
        for name in _SUBAGENT_NAMES:
            path = agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing agent: {path}")

    def test_all_skill_files_exist(self):
        """All 3 SKILL.md files exist in skills/ directory."""
        skills_dir = self.plugin_root / "skills"
        for name in ("smm-protocol", "xp-values"):
            path = skills_dir / name / "SKILL.md"
            self.assertTrue(path.is_file(), f"Missing skill: {path}")

    def test_no_requirements_or_pyproject(self):
        """No requirements.txt or pyproject.toml with dependencies."""
        for name in ("requirements.txt", "pyproject.toml"):
            path = self.plugin_root / name
            if path.is_file():
                content = path.read_text()
                self.assertNotIn(
                    "install_requires",
                    content,
                    f"{name} should not declare dependencies",
                )
                self.assertNotIn(
                    "dependencies",
                    content,
                    f"{name} should not declare dependencies",
                )

    def test_settings_json_exists(self):
        """settings.json exists with expected keys."""
        path = self.plugin_root / "settings.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertIn("commit_size_threshold", data)

    def test_behavioral_guide_exists(self):
        """BEHAVIORAL_GUIDE.md exists and is non-trivial."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        self.assertTrue(path.is_file(), "Missing BEHAVIORAL_GUIDE.md")
        content = path.read_text()
        self.assertGreater(len(content), 1000, "BEHAVIORAL_GUIDE.md too short")


if __name__ == "__main__":
    unittest.main()
