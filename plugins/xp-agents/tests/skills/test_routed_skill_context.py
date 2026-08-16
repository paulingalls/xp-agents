#!/usr/bin/env python3
"""The frontmatter context that review-cycle routing reasons from.

`review_cycle_done._TARGET_BY_NAME` keys `xp-review-plan` on the SKILL because
a FORKED skill's Skill call returns at completion, and deliberately omits
`xp-quality-review` in favour of the agent it spawns because an INLINE skill's
returns at launch. Flipping either frontmatter silently inverts that reasoning
— a forked /xp-quality-review would make the omitted entry correct again, and
an inlined /xp-review-plan would record its review before one had run — and
nothing else in the suite pins the classification per name.
"""

import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body


class TestRoutedSkillContext(unittest.TestCase):
    # skill name -> does its frontmatter declare `context: fork`?
    _ASSUMED: ClassVar[dict[str, bool]] = {
        "xp-review-plan": True,
        "xp-quality-review": False,
        "xp-assign": False,
    }

    def test_each_routed_skill_matches_its_assumed_context(self):
        for name, forked in self._ASSUMED.items():
            with self.subTest(skill=name):
                frontmatter, _ = _split_frontmatter_body(
                    (_PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text()
                )
                self.assertEqual("context: fork" in frontmatter, forked)


if __name__ == "__main__":
    unittest.main()
