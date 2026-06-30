#!/usr/bin/env python3
"""Pins kickoff Step 1 (retrospective) and Step 6 (housekeeper) to invoke their
Agent-tool subagents synchronously. The harness backgrounds Agent-tool subagents
by default; a backgrounded retrospective or housekeeper races the step-gated
kickoff sequence and trips the Stop housekeeping gate. Both passages must name
the lever explicitly so the LLM does not fall back to the async default.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "SKILL.md"

_SYNC_LEVER = "run_in_background:false"


def _slice_step(text: str, heading: str) -> str:
    """Return one `## Step ...` section, sliced to the next `## Step` header."""
    start = text.find(heading)
    if start < 0:
        return ""
    end = text.find("\n## Step", start + len(heading))
    return text[start:end] if end > 0 else text[start:]


class TestKickoffSynchronousSubagents(unittest.TestCase):
    """Step 1 and Step 6 must force synchronous Agent-tool invocation."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.step_1 = _slice_step(cls.text, "## Step 1")
        cls.step_6 = _slice_step(cls.text, "## Step 6")

    def test_step_1_specifies_synchronous_lever(self):
        self.assertTrue(self.step_1, "Step 1 region is empty")
        self.assertIn(_SYNC_LEVER, self.step_1)

    def test_step_6_specifies_synchronous_lever(self):
        self.assertTrue(self.step_6, "Step 6 region is empty")
        self.assertIn(_SYNC_LEVER, self.step_6)

    def test_step_6_retains_wait_for_completion_guidance(self):
        # Strengthening the lever must not drop the existing wait-for-completion
        # instruction — the two together gate the Stop housekeeping race.
        self.assertIn("background", self.step_6.lower())


if __name__ == "__main__":
    unittest.main()
