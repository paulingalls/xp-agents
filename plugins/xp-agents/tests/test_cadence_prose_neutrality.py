#!/usr/bin/env python3
"""Pins: teammate-facing prose stays cadence-neutral; spawn snippets stay portable.

story-008. Four rules across three surfaces:

1. No teammate-facing surface may assert ONE review cadence unconditionally.
   The session picks `commit` or `story`; under story cadence a per-commit
   review cycle is a duplicate the teammate pays for twice. Covers
   TEAMMATE_GUIDE.md (the guide injected into every teammate session) and
   xp-assign/SKILL.md (the prompt the lead writes for the teammate).

2. No shipped prose may use the bash-only `${VAR:+...}` conditional-expansion
   form for a spawn flag. zsh — the macOS default shell — expands it to ONE
   argv element (`--model sonnet`), which argparse rejects; a live spawn died
   on exit 1 this way. Regression pin.

3. The conditional-forwarding RULE must survive for BOTH `--model` and
   `--effort`. Rule 2 is satisfiable by deleting tier forwarding altogether;
   this pin makes that a failure instead of a pass. (`test_assign_tier_prose`
   only asserts the flag STRING appears somewhere in the body.)

4. seed_smm.py's cadence wisdom stays cadence-aware, and claims no
   gate-clearing role for `/simplify` — a harness built-in this plugin does
   not ship, so its behavior is not ours to assert. Only `/code-review` and
   `/xp-quality-review` set the per-commit review flag.

Rules 3 and 4 are green on arrival and load-bearing: they are what stops rules
1 and 2 from being "satisfied" by deleting the behavior instead of fixing it.
Rules 1 and 2 were observed red against this same file before their fixes
landed (6 failures) and arrive with them.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import _PLUGIN_ROOT, _slice

_GUIDE = _PLUGIN_ROOT / "TEAMMATE_GUIDE.md"
_ASSIGN = _PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md"
_SEED = _PLUGIN_ROOT / "smm" / "seed_smm.py"


def _rel(path: Path) -> str:
    return str(path.relative_to(_PLUGIN_ROOT))


class TestGuideCadenceNeutrality(unittest.TestCase):
    """TEAMMATE_GUIDE.md's Review Cycle section names both cadences."""

    @classmethod
    def setUpClass(cls):
        cls.guide = _GUIDE.read_text(encoding="utf-8")
        cls.review_cycle = _slice(cls.guide, "## Review Cycle", ("\n## ",))

    def test_review_cycle_section_exists(self):
        self.assertIn("## Review Cycle", self.guide)

    def test_quality_review_still_spawns_the_independent_reviewer(self):
        """Whatever the cadence, the review is the independent reviewer — a
        cadence rewrite must not quietly turn it into self-review."""
        self.assertIn("/xp-quality-review", self.review_cycle)
        self.assertIn("xp-code-reviewer", self.review_cycle)


class TestSpawnFlagConditionalForwarding(unittest.TestCase):
    """The forwarding RULE outlives the snippet that used to carry it."""

    def test_conditional_forwarding_rule_survives_for_both_flags(self):
        """Load-bearing counterweight to the portability pin: the RULE (forward
        the flag only when the story set the value) must still be stated for
        `--model` AND `--effort`. Deleting tier forwarding is not a fix."""
        body = _ASSIGN.read_text(encoding="utf-8")
        self.assertRegex(
            body,
            r"(?is)EXECUTOR_MODEL.{0,60}non-empty.{0,60}--model",
            "the --model conditional-forwarding rule is gone",
        )
        self.assertRegex(
            body,
            r"(?is)EXECUTOR_EFFORT.{0,60}non-empty.{0,60}--effort",
            "the --effort conditional-forwarding rule is gone",
        )


class TestSeedCadenceWisdom(unittest.TestCase):
    """The seeded cadence wisdom is the canonical wording; keep it honest."""

    @classmethod
    def setUpClass(cls):
        cls.seed = _SEED.read_text(encoding="utf-8")

    def test_seeded_wisdom_is_cadence_aware(self):
        self.assertIn("Review cadence (commit | story)", self.seed)
        self.assertIn("/xp-story-close", self.seed)
        self.assertIn("/xp-quality-review", self.seed)

    def test_no_surface_gives_simplify_a_gate_clearing_role(self):
        """`/simplify` is a harness built-in this plugin does not ship. Only
        `/code-review` appears in the review-cycle allowlist as an incoming
        skill name, so no shipped surface may credit `/simplify` with clearing
        the per-commit gate."""
        for path in (_SEED, _GUIDE, _ASSIGN):
            self.assertNotIn(
                "simplify",
                path.read_text(encoding="utf-8").lower(),
                f"{_rel(path)} mentions /simplify — its gate role is not ours "
                f"to assert",
            )


if __name__ == "__main__":
    unittest.main()
