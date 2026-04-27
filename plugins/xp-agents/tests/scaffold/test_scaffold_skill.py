#!/usr/bin/env python3
"""Tests for /xp-scaffold-acceptance SKILL.md and the analyzer concern wiring.

Markdown-shape assertions only — no script execution. Verifies that the skill
file (a) parses as a valid skill manifest, (b) embeds the verbatim doctrine
refusal text, (c) wires the M-1 detection helpers, and (d) leaves the M-2+
steps marked as reserved.

Cross-skill structural checks (frontmatter shape, directory layout) live in
tests/hooks/test_plugin_integrity.py via _ALL_SKILL_NAMES — the new skill
is registered there and inherits that coverage.
"""

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "xp-agents"
_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-scaffold-acceptance" / "SKILL.md"
_ANALYZER_PATH = _PLUGIN_ROOT / "agents" / "xp-system-analyzer.md"
_DOCTRINE_PATH = _REPO_ROOT / "docs" / "ideas" / "SCAFFOLDING_DOCTRINE.md"


def _frontmatter_body(text: str) -> tuple[str, str]:
    """Return (frontmatter, body) split on the closing `---` fence."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), match.group(2)


def _normalize_blockquote(text: str) -> str:
    """Strip markdown `>` prefixes and `*"…"*` italic-quote markers, collapse ws.

    Used to compare the doctrine refusal text against the SKILL.md embedding
    even when one wraps the lines slightly differently.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        lines.append(stripped)
    joined = " ".join(lines)
    joined = joined.replace('*"', "").replace('"*', "")
    return re.sub(r"\s+", " ", joined).strip()


def _doctrine_refusal_text() -> str:
    """Extract and normalize the §Teammate Interaction blockquote refusal."""
    doctrine = _DOCTRINE_PATH.read_text(encoding="utf-8")
    section = doctrine.split("## Teammate Interaction", 1)[1]
    section = section.split("\n## ", 1)[0]
    quote_lines: list[str] = []
    in_quote = False
    for line in section.splitlines():
        if line.lstrip().startswith(">"):
            in_quote = True
            quote_lines.append(line)
        elif in_quote:
            break
    return _normalize_blockquote("\n".join(quote_lines))


class TestSkillFrontmatter(unittest.TestCase):
    """Frontmatter shape — directory existence + name/description shape are
    enforced by tests/hooks/test_plugin_integrity.py via _ALL_SKILL_NAMES.
    The structured allowed-tools assertions live in
    TestSkillFrontmatterAllowedTools below."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _SKILL_PATH.read_text(encoding="utf-8")
        cls.fm, cls.body = _frontmatter_body(cls.text)

    def test_frontmatter_name(self) -> None:
        match = re.search(r"^name:\s*(\S+)", self.fm, re.MULTILINE)
        assert match is not None, "frontmatter must declare name:"
        self.assertEqual(match.group(1), "xp-scaffold-acceptance")

    def test_frontmatter_description_triggers_on_skill(self) -> None:
        self.assertIn("xp-scaffold-acceptance", self.fm.lower())


class TestSkillBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = _frontmatter_body(cls.text)

    def test_mentions_coordination_helper(self) -> None:
        self.assertIn("coordination.has_active_teammates", self.body)

    def test_mentions_read_acceptance_surfaces(self) -> None:
        self.assertIn("scaffold_detect.read_acceptance_surfaces", self.body)

    def test_mentions_detect_existing_tooling(self) -> None:
        self.assertIn("detect_existing_tooling", self.body)

    def test_mentions_canonical_tools_for(self) -> None:
        self.assertIn("canonical_tools_for", self.body)

    def test_contains_verbatim_doctrine_refusal(self) -> None:
        doctrine_refusal = _doctrine_refusal_text()
        skill_normalized = _normalize_blockquote(self.body)
        self.assertIn(
            doctrine_refusal,
            skill_normalized,
            "SKILL.md must embed the doctrine refusal text verbatim",
        )

    def test_step_3_uses_askuserquestion(self) -> None:
        step3_split = re.split(r"^##+\s+Step\s+3\b", self.body, flags=re.MULTILINE)
        self.assertGreater(len(step3_split), 1, "SKILL.md must have a Step 3 section")
        step3 = step3_split[1]
        next_step = re.search(r"^##+\s+Step\s+\d+\b", step3, flags=re.MULTILINE)
        if next_step:
            step3 = step3[: next_step.start()]
        self.assertIn("AskUserQuestion", step3)

    def test_reinvocation_stub_references_m5(self) -> None:
        self.assertIn("M-5", self.body)

    def test_reserved_steps_marked(self) -> None:
        self.assertRegex(self.body, r"Reserved for M-3")


def _gap_concern_block(text: str) -> str:
    """Return the bash code block that immediately follows the gap-concern
    raise instruction in xp-system-analyzer.md."""
    match = re.search(
        r"Raise concerns for gaps[\s\S]+?```bash\n(?P<body>[\s\S]+?)```",
        text,
    )
    return match.group("body") if match else ""


class TestAnalyzerConcernWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _ANALYZER_PATH.read_text(encoding="utf-8")
        cls.gap_block = _gap_concern_block(cls.text)

    def test_gap_block_extracted(self) -> None:
        self.assertNotEqual(
            self.gap_block, "", "gap-concern bash block not found in analyzer"
        )

    def test_gap_block_references_skill(self) -> None:
        self.assertIn(
            "/xp-scaffold-acceptance",
            self.gap_block,
            "gap-concern template must point at /xp-scaffold-acceptance",
        )

    def test_gap_block_does_not_say_install(self) -> None:
        self.assertNotIn("install the harness", self.gap_block)

    def test_analyzer_pins_canonical_surface_names(self) -> None:
        """Analyzer must enumerate the snake_case surface identifiers that
        scaffold_detect.canonical_tools_for keys off. Drift in either
        direction silently disables tool lookup in /xp-scaffold-acceptance."""
        for canonical in (
            "http_websocket",
            "browser",
            "cli",
            "sdk",
            "automation",
            "message_event",
        ):
            self.assertIn(
                f"`{canonical}`",
                self.text,
                f"analyzer must pin canonical surface name {canonical!r}",
            )


class TestSkillFrontmatterAllowedTools(unittest.TestCase):
    """Behavior-level frontmatter parse — replaces text-search-only assertions
    flagged by concern 355d7d282e30. Parses the YAML allowed-tools list and
    asserts on the structured set, not the raw string."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        fm, _ = _frontmatter_body(text)
        cls.allowed_tools = cls._parse_allowed_tools(fm)

    @staticmethod
    def _parse_allowed_tools(fm: str) -> list[str]:
        match = re.search(
            r"^allowed-tools:\s*\n((?:\s+-\s+[^\n]+\n?)+)",
            fm,
            flags=re.MULTILINE,
        )
        if not match:
            return []
        return [
            line.strip().lstrip("-").strip()
            for line in match.group(1).splitlines()
            if line.strip()
        ]

    def test_includes_websearch(self) -> None:
        self.assertIn("WebSearch", self.allowed_tools)

    def test_includes_askuserquestion(self) -> None:
        self.assertIn("AskUserQuestion", self.allowed_tools)

    def test_includes_read(self) -> None:
        self.assertIn("Read", self.allowed_tools)

    def test_no_edit_or_write_tool(self) -> None:
        for forbidden in ("Edit", "Write", "MultiEdit"):
            self.assertNotIn(
                forbidden,
                self.allowed_tools,
                f"M-2 must not declare {forbidden!r} — Steps 6-9 (writes) "
                "ship in M-3 onward",
            )


def _step_section(body: str, step_number: int) -> str:
    """Extract the prose for `## Step N` up to the next `## Step` header."""
    pattern = rf"^##+\s+Step\s+{step_number}\b"
    splits = re.split(pattern, body, flags=re.MULTILINE)
    if len(splits) < 2:
        return ""
    rest = splits[1]
    next_step = re.search(r"^##+\s+Step\s+\d+\b", rest, flags=re.MULTILINE)
    return rest[: next_step.start()] if next_step else rest


class TestSkillM2Wiring(unittest.TestCase):
    """M-2 wiring: Step 2 web-refresh, Step 4 build_plan, Step 5 confirm."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = _frontmatter_body(text)

    def test_step_2_uses_websearch_for_version_refresh(self) -> None:
        step2 = _step_section(self.body, 2)
        self.assertNotEqual(step2.strip(), "")
        self.assertIn("WebSearch", step2)
        self.assertIn("version", step2.lower())

    def test_step_2_handles_non_canonical_tool_decline(self) -> None:
        step2 = _step_section(self.body, 2)
        self.assertIn("decline_if_unreliable", step2)

    def test_step_4_calls_build_plan(self) -> None:
        step4 = _step_section(self.body, 4)
        self.assertIn("scaffold_plan.build_plan", step4)

    def test_step_5_calls_render_preview(self) -> None:
        step5 = _step_section(self.body, 5)
        self.assertIn("scaffold_plan.render_preview", step5)

    def test_step_5_uses_askuserquestion_with_three_options(self) -> None:
        step5 = _step_section(self.body, 5)
        self.assertIn("AskUserQuestion", step5)
        for option in ("yes", "show files", "no"):
            self.assertIn(option, step5.lower(), f"Step 5 missing option: {option!r}")

    def test_step_5_show_files_branch_documented(self) -> None:
        step5 = _step_section(self.body, 5)
        self.assertIn("show files", step5.lower())
        self.assertRegex(step5, r"file body|read.*back|Read each file")

    def test_no_writes_in_m2(self) -> None:
        for marker in ("Step 6", "Step 7", "Step 8", "Step 9"):
            section_index = self.body.find(f"## {marker}")
            self.assertGreater(section_index, -1, f"missing {marker} section")
        self.assertRegex(self.body, r"Reserved for M-3")


class TestSkillNoConfigFileSignalCaveat(unittest.TestCase):
    """Debt 8f2ca34871e1: SKILL.md must propagate NO_CONFIG_FILE_SIGNAL
    semantics — has_tooling=False for sdk/message_event surfaces means
    'no config-file signal,' not 'no tooling exists.'"""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = _frontmatter_body(text)

    def test_caveat_mentions_no_config_file_signal(self) -> None:
        self.assertIn("NO_CONFIG_FILE_SIGNAL", self.body)

    def test_caveat_names_sdk_and_message_event(self) -> None:
        self.assertIn("sdk", self.body)
        self.assertIn("message_event", self.body)

    def test_caveat_explains_signal_semantics(self) -> None:
        match = re.search(
            r"NO_CONFIG_FILE_SIGNAL[\s\S]{0,400}",
            self.body,
        )
        self.assertIsNotNone(match, "NO_CONFIG_FILE_SIGNAL caveat not found")
        caveat = match.group(0).lower()
        self.assertTrue(
            "config-file" in caveat or "no config" in caveat,
            "Caveat must mention the config-file-signal distinction",
        )


if __name__ == "__main__":
    unittest.main()
