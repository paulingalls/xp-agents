#!/usr/bin/env python3
"""Pin: every close SKILL.md's step list names the cycle-id release.

`scripts/_close_pipeline_shared.md` gained Step 6b — the consume that releases
the close-cycle id marker on every exit. The shared reference is pinned; the
per-mode step ENUMERATIONS were not, and all four said "Steps 5, 5b, and 6 …
then continue with Step 7". An agent following its skill's own list therefore
walks straight past 6b, which is the mechanical reason the release gets
skipped: the id then tags concerns raised after the close ended, and the next
close's `--cycle-id` count EXCLUDES them.

Prose pins cannot prove an agent runs the step; they prove the step is named in
the list the agent follows, which is what was missing.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_PLUGIN_ROOT = Path(__file__).parent.parent
_SHARED_PATH = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"
_MODES = ("story", "sprint", "plan", "free")
_SECTION_MARKER = "Apply shared close-pipeline reference"


def _skill_text(mode: str) -> str:
    return (_PLUGIN_ROOT / "skills" / f"xp-{mode}-close" / "SKILL.md").read_text(
        encoding="utf-8"
    )


class TestSharedReferenceDefinesStep6b(unittest.TestCase):
    def test_the_shared_reference_still_carries_step_6b(self):
        """Non-vacuity: the pins below are about the enumerations pointing at a
        step that exists."""
        self.assertIn("Step 6b", _SHARED_PATH.read_text(encoding="utf-8"))


class TestEveryCloseSkillEnumeratesStep6b(unittest.TestCase):
    def test_step_list_names_6b(self):
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertIn(
                    "6b",
                    _skill_text(mode),
                    f"xp-{mode}-close never names Step 6b, so an agent "
                    f"following its step list releases no cycle id",
                )

    def test_the_shared_reference_section_names_6b(self):
        """Specifically in the section that enumerates the shared steps — a
        mention anywhere else in the file is not the list the agent reads."""
        for mode in _MODES:
            with self.subTest(mode=mode):
                text = _skill_text(mode)
                start = text.index(_SECTION_MARKER)
                section = text[start : start + 600]
                self.assertIn("6b", section)

    def test_no_skill_still_calls_it_three_steps(self):
        """The count is the tell: "those three steps" is the enumeration that
        excluded 6b, and it reads as authoritative next to the shared file."""
        for mode in _MODES:
            with self.subTest(mode=mode):
                self.assertNotIn("those three steps", _skill_text(mode))


if __name__ == "__main__":
    unittest.main()
