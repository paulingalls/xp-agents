#!/usr/bin/env python3
"""xp-code-reviewer.md prose pins for sprint-104 story-001.

The three additions:
  Section 1  — state/lifecycle/concurrency angle bullet
  Section 1b — bounded self-verify with category-based spare-clause
  Section 1c — recognition of an inbound ## Review Focus block (written by
               story-003's xp-quality-review Step 1.5 on RISK=high)

Tests are prose pins: the agent is an LLM, so the deterministic guard is the
prompt prose itself. Sprint-103 attempted similar work and was abandoned at
close — the cross-language vocabulary guard (test 2) is the load-bearing
sprint-104 lesson (CLAUDE.md two-layer project-agnostic guardrail).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import _split_frontmatter_body
from conftest import _PLUGIN_ROOT

_AGENT_PROMPT = _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md"


def _section_slice(body: str, start_heading: str, end_heading: str) -> str:
    """Return the body slice between two headings (start inclusive, end exclusive).

    Both headings must appear; raises a clear AssertionError otherwise so
    the section-anchored assertions fail loud rather than silently shrink.
    """
    s = body.find(start_heading)
    e = body.find(end_heading, s + 1 if s != -1 else 0)
    if s == -1 or e == -1:
        raise AssertionError(
            f"Could not locate section bounds: start={start_heading!r} "
            f"found={s != -1}, end={end_heading!r} found={e != -1}"
        )
    return body[s:e]


class TestXpCodeReviewerProse(unittest.TestCase):
    """Pin the prose additions in xp-code-reviewer.md."""

    @classmethod
    def setUpClass(cls):
        text = _AGENT_PROMPT.read_text(encoding="utf-8")
        _, cls.body = _split_frontmatter_body(text)
        cls.lower = cls.body.lower()

    def test_section_1_lists_state_lifecycle_angle(self):
        """Section 1 (Correctness) includes a state/lifecycle/concurrency angle."""
        section_1 = _section_slice(self.body, "## 1.", "## 2.").lower()
        # The angle name itself must appear in Section 1.
        self.assertTrue(
            "state/lifecycle" in section_1 or "state / lifecycle" in section_1,
            "Section 1 must name a 'state/lifecycle' review angle",
        )
        # Concrete signal vocabulary covering the failure shapes the two
        # known regressions exhibited (latch-no-clear, marker-no-drain,
        # paired-lifecycle, async ordering).
        for keyword in ("latch", "marker", "lifecycle", "async"):
            self.assertIn(
                keyword,
                section_1,
                f"Section 1 state/lifecycle angle must mention {keyword!r}",
            )

    def test_state_lifecycle_angle_is_cross_language(self):
        """Anti-leak guard: the new angle uses generic CS vocabulary only.

        Sprint-103 leaked xp-agents internals into shipped prose three times.
        The plugin ships to any-language projects; Python-specific examples
        or xp-agents internal surface names break the cross-language
        guarantee (constraint plugin-cross-language-coverage; CLAUDE.md
        project-agnostic guardrail vocabulary layer).
        """
        section_1 = _section_slice(self.body, "## 1.", "## 2.")
        section_1_lower = section_1.lower()
        # xp-agents-internal surface names — the rule, not an illustrative example.
        for leak in (
            "accept_in_flight",
            "quality_review_done",
            "simplify_done",
            ".assign-pending",
            "review_cycle_done",
        ):
            self.assertNotIn(
                leak,
                section_1_lower,
                f"Section 1 must not leak xp-agents internal name {leak!r}",
            )
        # Language-specific gating leaks. `.py` would appear if the prose
        # named a Python file suffix; `python` would appear if the prose
        # singled out the language.
        self.assertNotIn(
            "python",
            section_1_lower,
            "Section 1 must not single out Python — agent reviews any language",
        )
        self.assertNotRegex(
            section_1,
            r"\.py\b",
            "Section 1 must not gate on a Python file suffix",
        )

    def test_section_1b_bounded_self_verify_exists(self):
        """Section 1b stands up the bounded self-verify pass."""
        self.assertIn(
            "## 1b",
            self.body,
            "xp-code-reviewer.md must have a Section 1b heading",
        )
        section_1b = _section_slice(self.body, "## 1b", "## 1c").lower()
        self.assertIn(
            "self-verify",
            section_1b,
            "Section 1b must name the self-verify pass",
        )
        # Bound: one pass, not iterative — the cost-faithful shape.
        self.assertTrue(
            "one " in section_1b or "bounded" in section_1b,
            "Section 1b must describe the pass as bounded (one pass)",
        )

    def test_self_verify_spares_state_lifecycle_by_default(self):
        """Section 1b uses a CATEGORY-based spare-clause, not uncertainty-bias.

        Sprint-103 lesson (design doc §What was actually good): spare
        sparse state-findings by category, refute style nitpicks. Do NOT
        adopt an uncertainty-based 'default-refuted' bias — uncertainty
        alone doesn't earn deletion of a state/lifecycle finding.
        """
        section_1b = _section_slice(self.body, "## 1b", "## 1c")
        section_1b_lower = section_1b.lower()
        # The category-based spare clause: state/lifecycle findings spared by default.
        self.assertRegex(
            section_1b_lower,
            r"spare[^.]{0,120}state/?\s?lifecycle",
            "Section 1b must explicitly spare state/lifecycle findings by default",
        )
        # The disclaimer of the wrong shape (uncertainty-bias / default-refuted).
        # Same-sentence proximity: `not` followed within 80 chars by the rejected term.
        self.assertRegex(
            section_1b_lower,
            r"\bnot\b[^.]{0,80}(uncertainty|default[-\s]?refuted)",
            "Section 1b must explicitly disclaim an uncertainty-bias / "
            "default-refuted framing",
        )

    def test_section_1c_recognizes_review_focus_block(self):
        """Section 1c declares recognition of the inbound ## Review Focus block.

        Story-003 wires xp-quality-review Step 1.5 to emit a `## Review
        Focus` block on RISK=high. The agent must recognize the block
        (verbatim heading) and elevate the listed angles.
        """
        self.assertIn(
            "## 1c",
            self.body,
            "xp-code-reviewer.md must have a Section 1c heading",
        )
        section_1c = _section_slice(self.body, "## 1c", "## 2.")
        # The block name must appear verbatim with its markdown heading hash
        # so the agent recognizes the prompt signal, not just the english word.
        self.assertIn(
            "## Review Focus",
            section_1c,
            "Section 1c must name the ## Review Focus block verbatim",
        )
        # Recognition behavior: elevate / hunt first / priority — at least one.
        section_1c_lower = section_1c.lower()
        verbs = ("elevate", "hunt first", "priority")
        self.assertTrue(
            any(verb in section_1c_lower for verb in verbs),
            "Section 1c must describe how the agent elevates the listed angles "
            "(elevate / hunt first / priority)",
        )


if __name__ == "__main__":
    unittest.main()
