#!/usr/bin/env python3
"""Per-skill sequential-discipline pin presence (story-003, sprint-098).

Every INLINE skill (step-gated, main-agent-driven) carries a self-contained
"Sequential discipline" pin countering the harness parallel-batch instinct;
a still-FORKED delegation skill has no inline steps and carries no pin.
story-013 converts xp-sprint-review and xp-system-context to inline
(each now carries the pin); xp-review-plan converts in the same story's
next commit. See SMM risk 9890b01327ad and PROCESS_GUIDE.md §Sequential
Discipline (the canonical wording the pins reuse).

Classification is derived, not hardcoded: a skill is forked iff its
frontmatter declares ``context: fork`` (same signal as
test_system_context_skill.test_skill_md_is_forked). New skills are
auto-classified, so the lists can't silently drift.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body

# Match the formatter-stable plain substring, not the bold "**Sequential
# discipline.**" markup — an em-dash/bold normalization must not silently
# break the pin while the prose still reads correctly (same precedent as
# test_skill_askuserquestion_discipline.MARKER = "Unconditional gate").
MARKER = "Sequential discipline"

_SKILLS_DIR = _PLUGIN_ROOT / "skills"
_EXPECTED_INLINE = 18
_EXPECTED_FORKED = 1


def _classify_skills() -> tuple[dict[str, str], dict[str, str]]:
    """Return (inline, forked) name -> body maps, split on ``context: fork``."""
    inline: dict[str, str] = {}
    forked: dict[str, str] = {}
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        name = skill_md.parent.name
        frontmatter, body = _split_frontmatter_body(skill_md.read_text())
        if "context: fork" in frontmatter:
            forked[name] = body
        else:
            inline[name] = body
    return inline, forked


class TestSequentialPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inline, cls.forked = _classify_skills()

    def test_classification_counts(self):
        """Guard the inline/forked split so a miscount surfaces loudly."""
        self.assertEqual(
            len(self.inline), _EXPECTED_INLINE, f"inline skills: {sorted(self.inline)}"
        )
        self.assertEqual(
            len(self.forked), _EXPECTED_FORKED, f"forked skills: {sorted(self.forked)}"
        )

    def test_every_inline_skill_has_pin(self):
        missing = sorted(n for n, body in self.inline.items() if MARKER not in body)
        self.assertEqual(missing, [], f"inline skills missing the pin: {missing}")

    def test_no_forked_skill_has_pin(self):
        present = sorted(n for n, body in self.forked.items() if MARKER in body)
        self.assertEqual(present, [], f"forked skills should carry no pin: {present}")


if __name__ == "__main__":
    unittest.main()
