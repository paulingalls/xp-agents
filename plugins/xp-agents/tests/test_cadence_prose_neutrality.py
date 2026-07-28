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

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import _PLUGIN_ROOT, _slice

_GUIDE = _PLUGIN_ROOT / "TEAMMATE_GUIDE.md"
_ASSIGN = _PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md"
_SEED = _PLUGIN_ROOT / "smm" / "seed_smm.py"

# `${NAME:+...}` — bash-only "expand only if set and non-empty".
_BASH_ONLY_ALT_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:\+")


def _shipped_prose() -> list[Path]:
    """Every shipped markdown surface: guides, agents, skills, shared templates."""
    files: list[Path] = []
    files += sorted(_PLUGIN_ROOT.glob("*.md"))
    files += sorted(_PLUGIN_ROOT.glob("agents/*.md"))
    files += sorted(_PLUGIN_ROOT.glob("skills/*/*.md"))
    files += sorted((_PLUGIN_ROOT / "scripts").rglob("*.md"))
    return [f for f in files if f.is_file()]


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

    def test_does_not_assert_a_per_commit_review_unconditionally(self):
        """The bare "Before each commit: /xp-quality-review" instruction is
        wrong for half the sessions — it must be conditioned on the cadence."""
        self.assertNotRegex(
            self.review_cycle,
            r"(?i)before each commit:\s*`?/xp-quality-review",
            "TEAMMATE_GUIDE.md asserts a per-commit review cycle unconditionally",
        )

    def test_names_both_cadences_and_where_story_cadence_reviews(self):
        self.assertRegex(self.review_cycle, r"(?i)commit cadence")
        self.assertRegex(self.review_cycle, r"(?i)story cadence")
        self.assertIn("/xp-story-close", self.review_cycle)

    def test_points_at_the_live_gate_rather_than_the_prose(self):
        """The commit gate reports the cadence in force, so a teammate reads
        live state instead of trusting a guide written before the choice.

        A proximity match (`gate` within 120 chars of `cadence`) is vacuous
        here — the story-cadence clause above already contains "cadence the
        per-commit gate defers", so deleting the pointer sentence left the pin
        green. Pin the two halves of the pointer instead: the gate REPORTS the
        cadence, and the teammate is told not to assume one.
        """
        self.assertRegex(
            self.review_cycle,
            r"(?is)gate\s+\S+\s+the\s+cadence",
            "TEAMMATE_GUIDE.md does not say the commit gate reports the "
            "cadence in force",
        )
        self.assertRegex(
            self.review_cycle,
            r"(?i)do(n't| not) assume",
            "TEAMMATE_GUIDE.md does not tell the teammate to read the live "
            "cadence rather than assume one",
        )


class TestAssignPromptCadenceVar(unittest.TestCase):
    """The lead's teammate prompt gets the cadence from the preload, not a guess."""

    @classmethod
    def setUpClass(cls):
        cls.body = _ASSIGN.read_text(encoding="utf-8")
        cls.preload = (
            _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"
        ).read_text(encoding="utf-8")

    def test_preload_emits_the_review_cadence(self):
        """A deterministic source: `_get_review_cadence` (already shared by the
        story-close and quality-review preloads), emitted as a KEY=value var."""
        self.assertIn("_get_review_cadence", self.preload)
        self.assertIn("REVIEW_CADENCE=", self.preload)

    def test_prompt_content_bullet_names_the_cadence_var(self):
        """The review-cycle bullet in Step 3's include-list must direct the lead
        at the emitted var. "Write the cadence the session set" is otherwise
        unactionable and the lead guesses — which is how a sibling story got a
        duplicate review cycle."""
        bullets = [
            line
            for line in self.body.splitlines()
            if re.search(r"(?i)review.cycle", line) and line.lstrip().startswith("-")
        ]
        self.assertTrue(bullets, "no review-cycle bullet in the include-list")
        self.assertTrue(
            any("REVIEW_CADENCE" in line for line in bullets),
            "the review-cycle prompt bullet does not name REVIEW_CADENCE:\n"
            + "\n".join(bullets),
        )


class TestSpawnFlagConditionalForwarding(unittest.TestCase):
    """The forwarding RULE outlives the snippet that used to carry it."""

    def test_no_bash_only_conditional_expansion_in_shipped_prose(self):
        """`${VAR:+--flag "$VAR"}` is portable inside a bash script, NOT in
        prose an agent pastes into the user's login shell: zsh — the macOS
        default — does not word-split the expansion, so argparse receives one
        argv element `--model sonnet` and rejects it. Verified live: a spawn
        died on exit 1 this way. It only fires when a tier is set, so it hides
        in every untiered run."""
        violations: list[str] = []
        for path in _shipped_prose():
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if _BASH_ONLY_ALT_RE.search(line):
                    violations.append(f"{_rel(path)}:{lineno}: {line.strip()}")
        self.assertEqual(
            violations,
            [],
            "bash-only ${VAR:+...} form in shipped prose — zsh passes it as a "
            "single argv element and argparse rejects it:\n" + "\n".join(violations),
        )

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
