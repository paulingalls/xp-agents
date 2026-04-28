#!/usr/bin/env python3
"""Tests asserting that QR + security-reviewer prompts no longer instruct
the LLM to author lifecycle status events.

Sprint-041 / story-003 — the hook (review_cycle_done.py) is now the single
producer of `qr_complete` / `security_complete` events. Skill/agent prompts
must not double-emit them.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_QR_SKILL = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"
_SECURITY_REVIEWER = _PLUGIN_ROOT / "agents" / "xp-security-reviewer.md"

_QR_PATTERN = re.compile(r"append\.sh.*Quality review complete", re.DOTALL)
_SECURITY_PATTERN = re.compile(r"append\.sh.*Security review complete", re.DOTALL)


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

    def test_security_reviewer_does_not_emit_security_review_complete(self):
        text = _SECURITY_REVIEWER.read_text()
        self.assertIsNone(
            _SECURITY_PATTERN.search(text),
            "xp-security-reviewer.md still instructs the LLM to "
            "append a 'Security review complete' event — hook is now the "
            "sole producer (story-002).",
        )


if __name__ == "__main__":
    unittest.main()
