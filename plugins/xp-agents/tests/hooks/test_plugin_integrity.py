#!/usr/bin/env python3
"""Tests for plugin file structure, milestone files, and plugin integrity.

Split from test_validation.py for file size management.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

_SUBAGENT_NAMES = (
    "xp-code-reviewer",
    "xp-housekeeper",
    "xp-plan-reviewer",
    "xp-retrospective",
    "xp-security-reviewer",
    "xp-sprint-reviewer",
    "xp-system-analyzer",
)

_ALL_SKILL_NAMES = (
    "xp-accept",
    "xp-kickoff",
    "xp-plan",
    "xp-quality-review",
    "xp-review-plan",
    "xp-scaffold-acceptance",
    "xp-security-triage",
    "xp-assign",
    "xp-sprint-review",
    "xp-sprint-start",
    "xp-system-context",
    "xp-work-selection",
)

# Inline skills with substantial instructional content (700-2500 token budget)
_CONTENT_SKILL_NAMES = (
    "xp-quality-review",
    "xp-sprint-start",
)


class TestMilestone6Files(unittest.TestCase):
    """Verify presence and content of M6 files."""

    def setUp(self):
        self.plugin_root = Path(__file__).parent.parent.parent

    def test_xp_values_exists(self):
        """XP_VALUES.md must exist at plugin root."""
        path = self.plugin_root / "XP_VALUES.md"
        self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_process_guide_exists(self):
        """PROCESS_GUIDE.md must exist at plugin root."""
        path = self.plugin_root / "PROCESS_GUIDE.md"
        self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_xp_values_token_budget(self):
        """XP_VALUES.md word count should estimate 150-1,000 tokens."""
        path = self.plugin_root / "XP_VALUES.md"
        if not path.exists():
            self.skipTest("XP_VALUES.md not yet created")
        words = len(path.read_text().split())
        estimated_tokens = words / 0.75
        self.assertGreaterEqual(
            estimated_tokens, 150, f"Too short: ~{estimated_tokens:.0f} tokens"
        )
        self.assertLessEqual(
            estimated_tokens, 1000, f"Too long: ~{estimated_tokens:.0f} tokens"
        )

    def test_process_guide_token_budget(self):
        """PROCESS_GUIDE.md word count should estimate 150-1,000 tokens."""
        path = self.plugin_root / "PROCESS_GUIDE.md"
        if not path.exists():
            self.skipTest("PROCESS_GUIDE.md not yet created")
        words = len(path.read_text().split())
        estimated_tokens = words / 0.75
        self.assertGreaterEqual(
            estimated_tokens, 150, f"Too short: ~{estimated_tokens:.0f} tokens"
        )
        self.assertLessEqual(
            estimated_tokens, 1000, f"Too long: ~{estimated_tokens:.0f} tokens"
        )

    def test_process_guide_includes_event_protocol(self):
        """PROCESS_GUIDE.md must include event recording protocol."""
        path = self.plugin_root / "PROCESS_GUIDE.md"
        if not path.exists():
            self.skipTest("PROCESS_GUIDE.md not yet created")
        content = path.read_text()
        self.assertIn("Event Types", content)
        self.assertIn("working_on", content)
        self.assertIn("references", content)

    def test_skill_directories_exist(self):
        """All skill dirs must exist with SKILL.md."""
        for name in _ALL_SKILL_NAMES:
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")

    def test_skill_frontmatter_valid(self):
        """Each SKILL.md must have valid YAML frontmatter with name + description."""
        for name in _ALL_SKILL_NAMES:
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
        """Content skills should be within 700-2500 token estimate."""
        for name in _CONTENT_SKILL_NAMES:
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            if not skill_file.exists():
                self.skipTest(f"{skill_file} not yet created")
            words = len(skill_file.read_text().split())
            estimated_tokens = words / 0.75
            self.assertGreaterEqual(
                estimated_tokens,
                700,
                f"{name} too short: ~{estimated_tokens:.0f} tokens",
            )
            self.assertLessEqual(
                estimated_tokens,
                2500,
                f"{name} too long: ~{estimated_tokens:.0f} tokens",
            )

    def test_xp_values_has_core_values(self):
        """XP_VALUES.md should cover XP values."""
        path = self.plugin_root / "XP_VALUES.md"
        if not path.exists():
            self.skipTest("XP_VALUES.md not yet created")
        content = path.read_text()
        self.assertIn("Honesty", content)
        self.assertIn("Courage", content)
        self.assertIn("Simplicity", content)

    def test_process_guide_no_contradictions(self):
        """Process guide should not contradict hook enforcement."""
        path = self.plugin_root / "PROCESS_GUIDE.md"
        if not path.exists():
            self.skipTest("PROCESS_GUIDE.md not yet created")
        content = path.read_text()
        self.assertNotIn("instead of hooks", content.lower())
        self.assertNotIn("ignore quality review", content.lower())
        self.assertIn("TDD", content)


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

    def test_body_mentions_append_sh(self):
        """Every subagent should reference append.sh for event writing."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            # Body is after the second ---
            parts = content.split("---", 2)
            body = parts[2] if len(parts) >= 3 else ""
            self.assertIn("append.sh", body, f"{name} body missing append.sh reference")

    def test_body_mentions_smm_content_trust(self):
        """Subagents that read SMM data should have the content trust section."""
        # xp-security-reviewer doesn't read the SMM — no trust section needed
        skip = {"xp-security-reviewer"}
        for name in _SUBAGENT_NAMES:
            if name in skip:
                continue
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertIn(
                "SMM Content Trust", content, f"{name} missing SMM Content Trust"
            )

    def test_xp_assign_has_no_agent_file(self):
        """xp-assign is an inline skill — no agent file should exist."""
        path = self.agents_dir / "xp-assign.md"
        self.assertFalse(
            path.exists(), f"xp-assign agent file should not exist: {path}"
        )

    def test_xp_assign_skill_is_inline(self):
        """xp-assign SKILL.md must not have context: fork or agent: field."""
        skill_file = (
            Path(__file__).parent.parent.parent / "skills" / "xp-assign" / "SKILL.md"
        )
        content = skill_file.read_text()
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        self.assertIsNotNone(match)
        fm = match.group(1)
        self.assertNotIn("context: fork", fm)
        self.assertNotIn("agent:", fm)


# ===========================================================================
# Quality Review Skill Structure
# ===========================================================================


class TestQualityReviewSkill(unittest.TestCase):
    """Quality review skill uses xp-code-reviewer subagent."""

    def setUp(self):
        self.skill_file = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-quality-review"
            / "SKILL.md"
        )
        self.content = self.skill_file.read_text()
        match = re.match(r"^---\n(.*?)\n---", self.content, re.DOTALL)
        self.fm = match.group(1) if match else ""

    def test_allowed_tools_includes_agent(self):
        """Quality review SKILL.md must allow the Agent tool."""
        self.assertIn("Agent", self.fm)

    def test_references_code_reviewer(self):
        """Quality review SKILL.md must reference xp-code-reviewer."""
        self.assertIn("xp-code-reviewer", self.content)


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

    def test_kickoff_skill_has_sprint_steps(self):
        """Kickoff SKILL.md must have the redesigned flow steps."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        self.assertIn("Execution Plan", content)
        self.assertIn("Sprint", content)
        self.assertIn("Work Selection", content)
        self.assertIn("Housekeeping", content)

    def test_kickoff_skill_has_read_tool(self):
        """M8b: kickoff SKILL.md must have Read in allowed-tools."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        # Extract frontmatter
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        self.assertIsNotNone(match)
        fm = match.group(1)
        self.assertIn("Read", fm)

    def test_kickoff_skill_no_question_triage_in_sprint_path(self):
        """M8b: sprint-active path should not call /xp-question-triage."""
        skill_file = self.plugin_root / "skills" / "xp-kickoff" / "SKILL.md"
        content = skill_file.read_text()
        # The SPRINT_ACTIVE subsection (between "SPRINT_ACTIVE" and
        # "no SPRINT_ACTIVE") should not mention question-triage
        if "SPRINT_ACTIVE" in content:
            after_sprint = content.split("SPRINT_ACTIVE")[1]
            fallback = after_sprint.find("no SPRINT_ACTIVE")
            sprint_path = after_sprint[:fallback] if fallback > 0 else after_sprint
            self.assertNotIn("xp-question-triage", sprint_path)

    def test_accept_skill_has_story_flow(self):
        """M8c: accept SKILL.md must have acceptance criteria verification."""
        skill_file = self.plugin_root / "skills" / "xp-accept" / "SKILL.md"
        content = skill_file.read_text()
        self.assertIn("acceptance criteria", content.lower())
        self.assertIn("done", content.lower())
        self.assertIn("deferred", content.lower())

    def test_hooks_json_has_sprint_stop_gate(self):
        """hooks.json Stop array must include sprint_stop_gate.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("sprint_stop_gate.py", content)

    def test_hooks_json_has_teammate_idle(self):
        """M13: hooks.json TeammateIdle must include teammate_idle.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("teammate_idle.py", content)
        self.assertIn("TeammateIdle", content)

    def test_hooks_json_has_task_completed(self):
        """M13: hooks.json TaskCompleted must include task_completed.py."""
        hooks_path = self.plugin_root / "hooks" / "hooks.json"
        content = hooks_path.read_text()
        self.assertIn("task_completed.py", content)
        self.assertIn("TaskCompleted", content)

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

    def test_no_settings_json(self):
        """settings.json should not exist — all config is hardcoded."""
        path = self.plugin_root / "settings.json"
        self.assertFalse(path.is_file())

    def test_guide_files_exist(self):
        """XP_VALUES.md and PROCESS_GUIDE.md exist and are non-trivial."""
        values = self.plugin_root / "XP_VALUES.md"
        process = self.plugin_root / "PROCESS_GUIDE.md"
        self.assertTrue(values.is_file(), "Missing XP_VALUES.md")
        self.assertTrue(process.is_file(), "Missing PROCESS_GUIDE.md")
        combined = values.read_text() + process.read_text()
        self.assertGreater(len(combined), 1000, "Guide files too short combined")


if __name__ == "__main__":
    unittest.main()
