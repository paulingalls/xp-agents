#!/usr/bin/env python3
"""Autonomy-nudge guard at unconditional skill AskUserQuestion gates.

A Claude Code `<system-reminder>` ("make the reasonable call") was
mis-applied as license to skip prescribed customer-input gates in
/xp-kickoff Step 2 and /xp-plan Step 1. See SMM risk cc16c407382a and
the matching wisdom entry. Other AskUserQuestion calls in the plugin
are inherently conditional ("if shown", per-item loops) and are NOT
pinned here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body


class TestAutonomyNudgeGuard(unittest.TestCase):
    # Match the ASCII prefix of "**Unconditional gate — do not skip.**" so
    # an em-dash normalization (e.g., auto-formatter rewriting "—" to "--")
    # does not silently break the pin while the prose still reads correctly.
    MARKER = "Unconditional gate"

    @classmethod
    def setUpClass(cls):
        _, cls.kickoff = _split_frontmatter_body(
            (_PLUGIN_ROOT / "skills/xp-kickoff/SKILL.md").read_text()
        )
        _, cls.plan = _split_frontmatter_body(
            (_PLUGIN_ROOT / "skills/xp-plan/SKILL.md").read_text()
        )

    def test_kickoff_step2_marker_in_region(self):
        start = self.kickoff.index("## Step 2: Session mode")
        end = self.kickoff.index("## Step 2.4:")
        self.assertIn(self.MARKER, self.kickoff[start:end])

    def test_plan_step1_marker_in_region(self):
        start = self.plan.index("### Step 1: Source Gathering")
        end = self.plan.index("### Step 2: Light Codebase Scan")
        self.assertIn(self.MARKER, self.plan[start:end])

    def test_plan_step1_header_labelled_always(self):
        self.assertIn("### Step 1: Source Gathering (ALWAYS)", self.plan)


if __name__ == "__main__":
    unittest.main()
