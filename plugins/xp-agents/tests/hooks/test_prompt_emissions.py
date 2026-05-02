#!/usr/bin/env python3
"""Tests asserting that the QR skill prompt does not instruct the LLM to
author the lifecycle status event the hook emits.

Sprint-041 / story-003 — review_cycle_done.py is the single producer of
`qr_complete` events. The QR skill prompt must not double-emit it.

The matching guard for the security-reviewer agent was dropped in M-5
(sprint-052) when story-001 deleted the agent itself.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_QR_SKILL = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"

_QR_PATTERN = re.compile(r"append\.sh.*Quality review complete", re.DOTALL)


class TestPromptEmissions(unittest.TestCase):
    """Skill/agent prompts must not author lifecycle events the hook emits."""

    def test_qr_skill_does_not_emit_quality_review_complete(self):
        text = _QR_SKILL.read_text()
        self.assertIsNone(
            _QR_PATTERN.search(text),
            "xp-quality-review/SKILL.md still instructs the LLM to "
            "append a 'Quality review complete' event — hook is now the "
            "sole producer (story-002).",
        )


if __name__ == "__main__":
    unittest.main()
