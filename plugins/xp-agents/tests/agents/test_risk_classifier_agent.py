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
  * sprint-111 M4: six project-agnostic signals + decision matrix +
    Design-Context down-rating, all project-agnostic (no baked-in plugin cap)

Budget is character-based only (AGENT_BUDGETS in test_agent_budgets.py, per
constraint 4e4f2861184f). The old line-based body bound was the suite's last
lines/bytes budget and was removed here as drift.
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

    # --- sprint-111 M4: broadened rubric -------------------------------------

    # The six canonical project-agnostic signal keywords (design doc
    # docs/ideas/RISK_CLASSIFIER_RUBRIC_BROADENING.md). story-002 maps each to a
    # reviewer enrichment angle; the names are an interface contract.
    _SIGNALS = (
        "path-traversal",
        "input-validation",
        "combinatorial-data-table",
        "cross-runtime-portability",
        "file-size-creep",
        "schema-cross-contract",
    )

    def test_body_names_all_six_signals(self):
        """All six project-agnostic signal keywords must appear in the rubric.

        The keywords are the SIGNALS= vocabulary story-002 consumes; a missing
        one silently drops a reviewer enrichment angle.
        """
        missing = [s for s in self._SIGNALS if s not in self.body]
        self.assertEqual(missing, [], f"rubric is missing signal keyword(s): {missing}")

    def test_body_has_decision_matrix(self):
        """An explicit low-vs-high decision section, not just signal prose.

        The classifier needs the rule that turns signals into a verdict; pin a
        'RISK=low only when' / 'RISK=high when' shape so the matrix is present.
        """
        # Normalize away markdown emphasis so backticks around `RISK=low`
        # don't break the contiguous phrase match.
        matrix = self.body_lower.replace("`", "")
        self.assertIn(
            "risk=low only when",
            matrix,
            "body must state the RISK=low gate ('RISK=low only when ...')",
        )
        self.assertIn(
            "risk=high when",
            matrix,
            "body must state the RISK=high trigger ('RISK=high when ...')",
        )

    def test_body_has_design_context_section(self):
        """`## Design Context` input heading + a down-rate instruction.

        story-003 passes the changed-file design/constraint block under this
        exact heading (interface contract). The rubric must tell the classifier
        to down-rate a diff that matches a documented host-project convention
        rather than false-flag a spec'd pattern as a novelty (wisdom
        f3c3aa218f9f).
        """
        self.assertRegex(
            self.body,
            r"(?m)^##\s+Design Context\s*$",
            "body must declare a `## Design Context` input heading "
            "(the heading story-003 passes the context block under)",
        )
        # The down-rate instruction: a documented/known convention match lowers
        # risk. Accept either canonical verb pairing.
        has_down_rate = "down-rate" in self.body_lower or "down rate" in self.body_lower
        has_convention = (
            "convention" in self.body_lower or "documented" in self.body_lower
        )
        down_rate = has_down_rate and has_convention
        self.assertTrue(
            down_rate,
            "body must instruct down-rating diffs that match a documented "
            "host-project convention",
        )

    def test_body_defers_size_threshold_to_host_project(self):
        """Project-agnostic gate (customer's key requirement).

        The plugin ships to any-language projects; the file-size signal must NOT
        bake in this plugin's own 500-line cap as the rule. Thresholds defer to
        the host project's own coding standards.
        """
        # No hardcoded line-cap constant masquerading as the rule.
        self.assertNotRegex(
            self.body,
            r"\b500\b",
            "rubric must not bake in the plugin's 500-line cap — defer to the "
            "host project's coding standards",
        )
        # Explicit deference to the host project's standards.
        self.assertRegex(
            self.body_lower,
            r"(host project|project'?s own|host[\s-]project'?s)",
            "file-size / threshold guidance must defer to the host project's "
            "own coding standards",
        )


if __name__ == "__main__":
    unittest.main()
