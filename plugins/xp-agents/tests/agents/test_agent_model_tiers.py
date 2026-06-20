#!/usr/bin/env python3
"""Per-agent model-tier pins.

The digest-fed curators (xp-retrospective, xp-housekeeper) consume a
bounded, pre-computed input and apply mechanical judgment, so they run on
the cheaper/faster Sonnet tier. The judgment-critical agents (the four
reviewers and the exploration-fed xp-system-analyzer) stay on `inherit`:
reviewers carry adversarial correctness/quality judgment, and the analyzer
reads broad codebase context (200k can bind) to emit a durable
system_context.json. This test pins the boundary so a future "downgrade
everything to Sonnet" sweep can't silently weaken the judgment-critical
agents.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _split_frontmatter_body

_AGENTS_DIR = _PLUGIN_ROOT / "agents"

# Digest-fed curators — deliberately pinned to Sonnet.
SONNET_AGENTS = ("xp-retrospective", "xp-housekeeper")

# Judgment-critical agents — must follow the session model.
INHERIT_AGENTS = (
    "xp-close-reviewer",
    "xp-code-reviewer",
    "xp-plan-reviewer",
    "xp-sprint-reviewer",
    "xp-system-analyzer",
)


def _agent_model(name: str) -> str:
    frontmatter, _ = _split_frontmatter_body((_AGENTS_DIR / f"{name}.md").read_text())
    match = re.search(r"^model:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
    assert match is not None, f"{name}.md has no `model:` frontmatter field"
    return match.group(1)


class TestAgentModelTiers(unittest.TestCase):
    def test_curators_pinned_to_sonnet(self):
        for name in SONNET_AGENTS:
            with self.subTest(agent=name):
                self.assertEqual(_agent_model(name), "sonnet")

    def test_judgment_agents_inherit_session_model(self):
        for name in INHERIT_AGENTS:
            with self.subTest(agent=name):
                self.assertEqual(_agent_model(name), "inherit")


if __name__ == "__main__":
    unittest.main()
