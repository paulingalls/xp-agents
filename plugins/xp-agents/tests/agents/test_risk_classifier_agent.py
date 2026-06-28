#!/usr/bin/env python3
"""xp-risk-classifier.md frontmatter + prose pins for sprint-104 story-002.

The classifier reads a diff and returns RISK=high|low on the first line.
Spawned by /xp-quality-review Step 1.4 (MODE=self-find only) on
per-increment review; gates the single enriched xp-code-reviewer spawn
on RISK=high.

Pins:
  * model: haiku — first haiku-tier agent in the plugin
  * tools: Read only (no Bash/Edit/Write/Grep/Glob) — anti-prompt-injection
  * STRICT first-line RISK=high|low output contract (not substring scan)
  * cross-language framing (sprint-103 lesson: LLM judgment, not regex)
  * anti-prompt-injection clause (diff content is untrusted user code)
  * body line bound (sanity backstop separate from AGENT_BUDGETS)
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import _split_frontmatter_body
from conftest import _PLUGIN_ROOT

_AGENT_PROMPT = _PLUGIN_ROOT / "agents" / "xp-risk-classifier.md"


class TestRiskClassifierAgent(unittest.TestCase):
    """Pin the frontmatter shape and load-bearing prose clauses."""

    @classmethod
    def setUpClass(cls):
        text = _AGENT_PROMPT.read_text(encoding="utf-8")
        cls.frontmatter, cls.body = _split_frontmatter_body(text)
        cls.body_lower = cls.body.lower()

    def test_frontmatter_model_haiku(self):
        """model: haiku — the first haiku-tier agent in the plugin."""
        match = re.search(r"^model:\s*(\S+)\s*$", self.frontmatter, re.MULTILINE)
        self.assertIsNotNone(
            match, "xp-risk-classifier.md must have a `model:` frontmatter field"
        )
        assert match is not None  # pyright narrowing
        self.assertEqual(match.group(1), "haiku")

    def test_frontmatter_tools_read_only(self):
        """tools: Read — no Bash, no Edit, no Write, no Grep, no Glob.

        The diff arrives in the prompt; the classifier never needs to mutate.
        Excluding Bash is the anti-prompt-injection guardrail — embedded
        directives in untrusted user code cannot trigger shell execution.
        """
        match = re.search(r"^tools:\s*(.+?)\s*$", self.frontmatter, re.MULTILINE)
        self.assertIsNotNone(
            match, "xp-risk-classifier.md must have a `tools:` frontmatter field"
        )
        assert match is not None  # pyright narrowing
        tools_value = match.group(1).strip()
        self.assertEqual(
            tools_value,
            "Read",
            "tools: must be exactly `Read` — no Bash/Edit/Write/Grep/Glob",
        )

    def test_body_declares_strict_first_line_output_contract(self):
        """STRICT first-line `RISK=high|low` + optional `SIGNALS=` second line.

        Sprint-103 lesson: substring scan over the full response is wrong
        (narrative tails legitimately contain the word RISK). Story-003's
        parser will read only the first line.
        """
        # Both output values must appear so the agent knows what to emit.
        self.assertIn("RISK=high", self.body)
        self.assertIn("RISK=low", self.body)
        # The "first line" discipline must be explicit (not just example output).
        self.assertRegex(
            self.body_lower,
            r"first[\s-]line",
            "body must explicitly name the first-line output discipline",
        )
        # The optional SIGNALS shape must be documented so the parser knows it.
        self.assertIn("SIGNALS=", self.body)

    def test_body_has_cross_language_framing(self):
        """Cross-language by LLM judgment, NOT per-language regex.

        Mirrors story-001's anti-leak guard. The plugin ships to any
        language; per-language regex / file-suffix gating is the
        sprint-103 leak the LLM-judged classifier is designed to fix.
        """
        # Generic-language framing must be present.
        framing_present = (
            "any language" in self.body_lower or "language-agnostic" in self.body_lower
        )
        self.assertTrue(
            framing_present,
            "body must declare cross-language scope (any language/language-agnostic)",
        )
        # Explicit disclaimer of per-language regex / suffix / extension gating.
        # Same-sentence proximity: 'not' followed within 80 chars by rejected term.
        self.assertRegex(
            self.body_lower,
            r"\bnot\b[^.]{0,80}(per[\s-]?language|regex|extension|suffix)",
            "body must disclaim per-language regex / suffix / extension gating",
        )

    def test_body_has_anti_prompt_injection_clause(self):
        """Diff content is untrusted user code; treat as data, not instructions."""
        # The canonical phrasing other agents use.
        canonical_a = "informational, not instructional" in self.body_lower
        canonical_b = (
            "treat" in self.body_lower
            and "as data" in self.body_lower
            and "not instruction" in self.body_lower
        )
        self.assertTrue(
            canonical_a or canonical_b,
            "body must declare diff content as informational/data, not instructional",
        )
        # Explicit directive language to not follow / not execute embedded text.
        self.assertRegex(
            self.body_lower,
            r"do not (follow|execute)",
            "body must tell the agent not to follow/execute embedded directives",
        )

    def test_body_under_haiku_line_budget(self):
        """Sanity backstop in case AGENT_BUDGETS registration is missed.

        Haiku tier targets ~35 body lines; AGENT_BUDGETS allots 50. This
        test asserts the same body-only bound so a forgotten budget
        registration still fails red here.
        """
        trailing = 1 if self.body and not self.body.endswith("\n") else 0
        body_lines = self.body.count("\n") + trailing
        self.assertLessEqual(
            body_lines,
            50,
            f"body has {body_lines} lines; haiku tier budget is 50",
        )


if __name__ == "__main__":
    unittest.main()
