#!/usr/bin/env python3
"""Tests for plugin file structure, milestone files, and plugin integrity.

Split from test_validation.py for file size management, then split again
from test_plugin_integrity.py for the same reason. This file covers
release-artifact sync (CHANGELOG/plugin.json version pins), the M6 guide
and skill files, and the M6.5 subagent files + quality-review skill
structure. See test_plugin_integrity_structure_and_close.py for the M7
marketplace/hooks.json structural checks and the close-skill doctrine
pins.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT

_SUBAGENT_NAMES = (
    "xp-code-reviewer",
    "xp-housekeeper",
    "xp-plan-reviewer",
    "xp-retrospective",
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


_PLUGIN_JSON = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
_REPO_ROOT = _PLUGIN_ROOT.parent.parent
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"
# v1-v3 history was archived at the v4.0 cut; pre-v4 fact pins read from here.
_CHANGELOG_PRE_V4 = _REPO_ROOT / "changelog_pre_v4.md"


_VERSION_HEADING_RE = re.compile(r"^## v(\d+\.\d+\.\d+)\b")


class TestReleaseSync(unittest.TestCase):
    """Structural checks that catch desynchronized release artifacts.

    Replaces the old per-version pin classes (TestV3xxRelease) — those
    needed a rename + constant update on every release and added noise
    to release diffs without catching what actually matters. These two
    checks work for every version forever.
    """

    def test_plugin_version_matches_changelog_top_entry(self):
        """plugin.json `version` must equal the version in the topmost
        `## vX.Y.Z` heading of CHANGELOG.md. Catches the case where a
        manifest bump shipped without a CHANGELOG entry, or vice versa.
        """
        manifest_version = json.loads(_PLUGIN_JSON.read_text())["version"]
        for line in _CHANGELOG.read_text().splitlines():
            match = _VERSION_HEADING_RE.match(line)
            if match:
                changelog_version = match.group(1)
                self.assertEqual(
                    manifest_version,
                    changelog_version,
                    f"plugin.json version {manifest_version!r} doesn't match "
                    f"CHANGELOG top entry vX.Y.Z {changelog_version!r}. "
                    "Bump both together.",
                )
                return
        self.fail("CHANGELOG.md has no `## vX.Y.Z` heading — the file shape changed.")

    def test_changelog_top_entry_format(self):
        """Top entry must follow `## vX.Y.Z — <title>` (em-dash, then
        prose). Catches malformed headings that would break the version
        match above.
        """
        for line in _CHANGELOG.read_text().splitlines():
            if line.startswith("## "):
                # First non-empty heading must be a version entry.
                self.assertRegex(
                    line,
                    r"^## v\d+\.\d+\.\d+ — .+$",
                    f"CHANGELOG top entry must match `## vX.Y.Z — <title>` "
                    f"(em-dash); got: {line!r}",
                )
                return
        self.fail("CHANGELOG.md has no `## ` headings at all.")


class TestChangelogFactsPins(unittest.TestCase):
    """Per-release fact pins for entries with load-bearing content.

    Additive — each test pins specific facts in a specific historical
    entry that a future edit must not silently drop. Adding a new
    test here is opt-in (only when an entry's facts are load-bearing
    enough to warrant it); release commits don't need to touch this
    class unless the release itself has such facts.
    """

    def test_changelog_v3_1_0_names_security_migration(self):
        # Pin the load-bearing M-8 facts so a future edit can't quietly
        # drop them: the migration target, the deletions, and the
        # additive metadata key. Reads from the archived pre-v4 changelog
        # (the v4.0 release cut split history out of CHANGELOG.md).
        content = _CHANGELOG_PRE_V4.read_text()
        # Scope to the v3.1.0 section only.
        v310_start = content.find("## v3.1.0")
        v310_end = content.find("\n## ", v310_start + 1)
        if v310_end == -1:
            v310_end = len(content)
        section = content[v310_start:v310_end]
        for needle in (
            "Step 4.5",
            "/security-review",
            "xp-accept",
            "xp-close-reviewer",
            "metadata.kind",
        ):
            with self.subTest(needle=needle):
                self.assertIn(
                    needle,
                    section,
                    f"v3.1.0 CHANGELOG entry must name {needle!r}",
                )


class TestMilestone6Files(unittest.TestCase):
    """Verify presence and content of M6 files."""

    def setUp(self):
        self.plugin_root = _PLUGIN_ROOT

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
        """PROCESS_GUIDE.md word count should estimate 150-1,450 tokens.

        Injected to the main agent only (session_start + review_cycle_done),
        never to subagents — so the cap is generous relative to the per-
        subagent guides. Bumped 1100→1300 for the Sequential Discipline section.

        Bumped 1300→1450 (story-018). The guide sat at ~1296 estimated tokens,
        i.e. 99.7% of cap, so ANY addition breached it — while the sibling
        CHARACTER budget in tests/test_guide_budgets.py still showed ~700 chars
        of room. The two budgets disagree about how much space exists; that is
        worth knowing before the next editor trusts either one alone.

        The addition was mandatory rather than elective: this file documented
        an empty `stack.test_command` as THE auto-merge off switch, and
        story-018 added a second way to be off (a command whose exit status
        never reaches the shell). Leaving that uncorrected would be the same
        claim-vs-coverage defect the story exists to fix. Trimmed to the
        minimum first — the narrowing tradeoff is stated in full where the
        customer actually confirms it, in the analyzer prompt, not here.
        """
        path = self.plugin_root / "PROCESS_GUIDE.md"
        if not path.exists():
            self.skipTest("PROCESS_GUIDE.md not yet created")
        words = len(path.read_text().split())
        estimated_tokens = words / 0.75
        self.assertGreaterEqual(
            estimated_tokens, 150, f"Too short: ~{estimated_tokens:.0f} tokens"
        )
        self.assertLessEqual(
            estimated_tokens, 1450, f"Too long: ~{estimated_tokens:.0f} tokens"
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

    def test_process_guide_includes_pillars(self):
        """PROCESS_GUIDE.md must define all four SMM pillars.

        Scopes the assertion to the `## Pillars` section so the four
        pillar names can't drift to incidental mentions elsewhere
        (e.g. the Event Types table column).
        """
        content = (self.plugin_root / "PROCESS_GUIDE.md").read_text()
        pillars_idx = content.find("## Pillars")
        self.assertNotEqual(pillars_idx, -1, "PROCESS_GUIDE.md missing '## Pillars'")
        section_end = content.find("\n## ", pillars_idx + 1)
        section = content[pillars_idx : section_end if section_end != -1 else None]
        for pillar in ("Intent", "Constraints", "Risks", "Wisdom"):
            self.assertIn(pillar, section, f"Pillar {pillar!r} not in Pillars section")
        # Pin the proactive-mindset directive: anchor includes the trigger
        # phrase ("at plan or sprint start") so a future edit that demotes
        # the line from a directive to a passive mention still trips the test.
        self.assertIn(
            "Read Intent and Risks at plan or sprint start",
            section,
            "Pillars section missing proactive-mindset directive",
        )

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
            assert match is not None, f"{name}/SKILL.md frontmatter not closed"
            fm = match.group(1)
            self.assertIn("name:", fm, f"{name}/SKILL.md missing 'name' field")
            self.assertIn(
                "description:", fm, f"{name}/SKILL.md missing 'description' field"
            )
            # Name should match directory
            name_match = re.search(r"name:\s*(\S+)", fm)
            assert name_match is not None
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

    def test_process_guide_refactor_mode_covers_new_primitives(self):
        """Refactor-mode prose must require behavior tests for new primitives.

        Codified after git_hooks.py consolidation shipped without coverage
        for its new primitives — original-caller tests left them as an
        implicit spec.
        """
        path = self.plugin_root / "PROCESS_GUIDE.md"
        if not path.exists():
            self.skipTest("PROCESS_GUIDE.md not yet created")
        content = path.read_text()
        refactor_idx = content.find("### Refactor Mode")
        self.assertNotEqual(
            refactor_idx, -1, "PROCESS_GUIDE.md missing '### Refactor Mode' section"
        )
        section_end = content.find("\n### ", refactor_idx + 1)
        section = content[refactor_idx : section_end if section_end != -1 else None]
        self.assertIn("new primitive", section.lower())
        self.assertIn("behavior test", section.lower())


class TestAgentFilesM65(unittest.TestCase):
    """Verify all plugin subagent files exist with correct frontmatter."""

    def setUp(self):
        self.agents_dir = _PLUGIN_ROOT / "agents"

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
            assert match is not None, f"{name} missing name field"
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
        for name in _SUBAGENT_NAMES:
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
        skill_file = _PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md"
        content = skill_file.read_text()
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert match is not None
        fm = match.group(1)
        self.assertNotIn("context: fork", fm)
        self.assertNotIn("agent:", fm)


# ===========================================================================
# Quality Review Skill Structure
# ===========================================================================


class TestQualityReviewSkill(unittest.TestCase):
    """Quality review skill uses xp-code-reviewer subagent."""

    def setUp(self):
        self.skill_file = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"
        self.content = self.skill_file.read_text()
        match = re.match(r"^---\n(.*?)\n---", self.content, re.DOTALL)
        self.fm = match.group(1) if match else ""

    def test_allowed_tools_includes_agent(self):
        """Quality review SKILL.md must allow the Agent tool."""
        self.assertIn("Agent", self.fm)

    def test_references_code_reviewer(self):
        """Quality review SKILL.md must reference xp-code-reviewer."""
        self.assertIn("xp-code-reviewer", self.content)


if __name__ == "__main__":
    unittest.main()
