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
    enforced by tests/hooks/test_plugin_integrity.py via _ALL_SKILL_NAMES."""

    def setUp(self) -> None:
        self.text = _SKILL_PATH.read_text(encoding="utf-8")
        self.fm, self.body = _frontmatter_body(self.text)

    def test_frontmatter_name(self) -> None:
        match = re.search(r"^name:\s*(\S+)", self.fm, re.MULTILINE)
        assert match is not None, "frontmatter must declare name:"
        self.assertEqual(match.group(1), "xp-scaffold-acceptance")

    def test_frontmatter_description_triggers_on_skill(self) -> None:
        self.assertIn("xp-scaffold-acceptance", self.fm.lower())

    def test_frontmatter_declares_allowed_tools(self) -> None:
        self.assertIn("allowed-tools:", self.fm)


class TestSkillBody(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _SKILL_PATH.read_text(encoding="utf-8")
        _, self.body = _frontmatter_body(self.text)

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
        self.assertRegex(self.body, r"Reserved for M-2")


def _gap_concern_block(text: str) -> str:
    """Return the bash code block that immediately follows the gap-concern
    raise instruction in xp-system-analyzer.md."""
    match = re.search(
        r"Raise concerns for gaps[\s\S]+?```bash\n(?P<body>[\s\S]+?)```",
        text,
    )
    return match.group("body") if match else ""


class TestAnalyzerConcernWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _ANALYZER_PATH.read_text(encoding="utf-8")
        self.gap_block = _gap_concern_block(self.text)

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


if __name__ == "__main__":
    unittest.main()
