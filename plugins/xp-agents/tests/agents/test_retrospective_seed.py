#!/usr/bin/env python3
"""xp-retrospective seed-retro path: empty/missing RETRO_INPUT.

/xp-kickoff Step 1 invokes xp-retrospective unconditionally. On a fresh
project there is no `.retro-input.json`, so the agent prompt must contain
explicit instructions for emitting a seed retrospective (Keep + Try, no
Fix) and saving it like any other retro — adopting a Try requires record
+ do (Wisdom invariant), so the seed path is NOT allowed to short-circuit
save_retrospective.py.

These are prompt-content assertions (the agent is an LLM; the deterministic
guard is the prompt instructions themselves).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_AGENT_PROMPT = _PLUGIN_ROOT / "agents" / "xp-retrospective.md"


class TestRetrospectiveSeedPath(unittest.TestCase):
    """Empty/missing RETRO_INPUT branch in xp-retrospective.md."""

    @classmethod
    def setUpClass(cls):
        cls.content = _AGENT_PROMPT.read_text()
        cls.lower = cls.content.lower()

    def test_no_legacy_insufficient_data_short_circuit(self):
        """The 'Insufficient data... and stop' early return is gone.

        A missing .retro-input.json is the first-session seed case, not
        a refusal case.
        """
        self.assertNotIn("Insufficient data for meaningful retrospective", self.content)

    def test_seed_retro_section_present(self):
        """A dedicated seed-retro section exists and names the trigger condition."""
        # Section heading the agent can navigate to. Hyphenless 'seed retro'
        # OR 'seed retrospective' both acceptable headings.
        self.assertTrue(
            "seed retro" in self.lower or "seed retrospective" in self.lower,
            "xp-retrospective.md must have a seed-retro section "
            "for the empty/missing RETRO_INPUT case",
        )
        # Must explicitly name the trigger.
        self.assertIn(".retro-input.json", self.content)

    def test_seed_keep_framing(self):
        """Seed Keeps are framed around adopting the XP process."""
        # The prompt must instruct the LLM to frame Keeps around XP adoption,
        # not invent observations from non-existent events.
        self.assertTrue(
            "adopting" in self.lower and "xp" in self.lower,
            "Seed retro instructions must frame Keep items around adopting XP",
        )

    def test_seed_try_framing(self):
        """Seed Tries are framed as 'try running <skill>' suggestions."""
        # Tries on a fresh project can't reference past events — they must be
        # actionable next-step skill suggestions.
        self.assertIn("try running", self.lower)

    def test_seed_no_fix_invariant(self):
        """Seed retro emits zero Fix items — there is no failure pattern yet."""
        # Prompt must explicitly say "no Fix" / "zero Fix" / "0 Fix" so the
        # LLM does not fabricate Fix items from speculation.
        self.assertTrue(
            "no fix" in self.lower or "zero fix" in self.lower or "0 fix" in self.lower,
            "Seed retro instructions must state the no-Fix invariant",
        )

    def test_seed_path_still_saves(self):
        """Seed must call save_retrospective.py — record + do (Wisdom)."""
        # The Actions section already names save_retrospective.py; ensure the
        # seed-retro section does NOT carve out an exception that bypasses it.
        # Cheap structural check: the prompt's existing "MUST complete BOTH
        # actions" / save mandate stays intact AND no opt-out language exists
        # for the seed path.
        self.assertIn("save_retrospective.py", self.content)
        # No exemption phrasing for the seed path.
        forbidden = ("skip the save", "do not save", "no need to save")
        for phrase in forbidden:
            self.assertNotIn(
                phrase,
                self.lower,
                f"Seed-retro path must not bypass save: forbidden phrase {phrase!r}",
            )


class TestRetrospectivePopulatedPathPreserved(unittest.TestCase):
    """Regression guard: populated-input path is unchanged.

    Acceptance criterion 3: existing Keep/Fix/Try analysis on a populated
    RETRO_INPUT must be preserved — only the empty branch is new.
    """

    @classmethod
    def setUpClass(cls):
        cls.content = _AGENT_PROMPT.read_text()

    def test_keep_fix_try_framework_intact(self):
        self.assertIn("Keep / Fix / Try", self.content)

    def test_xp_value_lenses_intact(self):
        for value in ("Honesty", "Communication", "Courage", "Simplicity", "Feedback"):
            self.assertIn(value, self.content)

    def test_pre_computed_flags_intact(self):
        self.assertIn("digest.flags", self.content)

    def test_event_ref_validation_intact(self):
        self.assertIn("Validate every event_ref", self.content)


if __name__ == "__main__":
    unittest.main()
