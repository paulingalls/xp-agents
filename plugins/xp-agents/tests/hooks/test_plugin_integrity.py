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
    "xp-retrospective",
    "xp-plan-reviewer",
    "xp-security-reviewer",
)


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
        for name in ("xp-smm-protocol",):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")

    def test_skill_frontmatter_valid(self):
        """Each SKILL.md must have valid YAML frontmatter with name + description."""
        for name in ("xp-smm-protocol",):
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
        for name in ("xp-smm-protocol",):
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

    def test_skills_include_smm_protocol(self):
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            parts = content.split("---", 2)
            fm = parts[1]
            self.assertIn("xp-smm-protocol", fm, f"{name} missing smm-protocol skill")

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
        for name in ("xp-smm-protocol",):
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
