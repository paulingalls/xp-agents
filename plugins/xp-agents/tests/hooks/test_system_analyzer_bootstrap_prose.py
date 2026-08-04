#!/usr/bin/env python3
"""The analyzer's worktree-bootstrap prose — the OTHER writer of that field.

Extracted from `test_system_analyzer_prompt.py` for the same reason its
surface-prose sibling was: that module sits against the tree's 450-line band,
so growth there is forbidden and extraction is the only legal move. This group
is cohesive on its own — it shares no fixture with the maxlength-sync and
update-mode tests it left behind, and it is the natural home for the next pin
on this field.

WHAT IS PINNED, AND WHAT IS DELIBERATELY NOT.

`stack.worktree_bootstrap` has two writers: this agent, which records a command
the repository already DOCUMENTS, and `/xp-scaffold-worktree`, which declares
one only after re-measuring proves it closed a real gap.

The agent's rule against inventing or assembling a command is NOT under
revision here, and `test_the_never_invent_rule_is_still_stated` exists to keep
it that way — a measurement over two real repositories vindicated it, and a
narrowing that quietly spent it would be a reversal wearing a clarification's
clothes.

The residual is narrower and had never been stated: documented is not measured.
The same measurement tried two plausible candidates, both exited 0, and one
closed nothing at all. So a value this agent records has to SAY it is
unverified, and name the skill that can verify it — otherwise it is
indistinguishable from one a verification produced, which is exactly the false
green the whole measurement exists to kill.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ANALYZER = Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"

# Wide enough to hold the whole bootstrap section as it stands (~1600 chars).
# Scoped rather than tree-wide so an `unverified` written about something else
# elsewhere in the prompt cannot false-green these pins; bump the window rather
# than widening the scan if the section grows.
_WINDOW_CHARS = 1800


class TestSystemAnalyzerMarksBootstrapUnverified(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = _ANALYZER.read_text(encoding="utf-8")
        anchor = "### Step 3.75"
        assert anchor in cls.content, "the bootstrap-detection heading drifted"
        start = cls.content.index(anchor)
        cls.window = cls.content[start : start + _WINDOW_CHARS]

    def test_the_never_invent_rule_is_still_stated(self):
        """The control. A narrowing that spent this rule would be a reversal,
        and every assertion below would still pass without it."""
        self.assertIn("Never invent one", self.window)

    def test_a_recorded_command_is_marked_unverified(self):
        self.assertIn(
            "unverified",
            self.window,
            "the analyzer records a documented command without measuring "
            "whether it closes a gap — say so, or the value reads as verified",
        )

    def test_the_verifying_skill_is_named(self):
        """An unverified marker with no way to resolve it is a dead end."""
        self.assertIn(
            "/xp-scaffold-worktree",
            self.window,
            "point at the skill that verifies the field, not merely at the "
            "fact that the value is unverified",
        )


if __name__ == "__main__":
    unittest.main()
