#!/usr/bin/env python3
"""Per-agent model-tier pins.

The digest-fed curators (xp-retrospective, xp-housekeeper) consume a
bounded, pre-computed input and apply mechanical judgment, so they run on
the cheaper/faster Sonnet tier. The judgment-critical agents (the four
reviewers and the exploration-fed xp-system-analyzer) are pinned to `opus`
(standard 200k, NOT the session's `[1m]` 1M-context beta): they carry
adversarial correctness/quality judgment and the analyzer reads broad
codebase context, so they need an Opus floor — guaranteed regardless of the
user's session model — while shedding the slower, more capacity-constrained
1M endpoint. This test pins the boundary so a future "downgrade everything to
Sonnet" sweep can't silently weaken the judgment-critical agents, and so no
agent silently re-acquires the `[1m]` variant.

No agent currently pins to Haiku — sprint-113 removed the risk classifier, the
only single-shot classification agent. The "haiku = classifiers" tiering policy
still stands for a future classification agent (see the Constraints pillar); it
just has no in-repo user today, so there is no Haiku tier list to pin here.
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

# Judgment-critical agents — pinned to Opus (200k, decoupled from session [1m]).
OPUS_AGENTS = (
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

    def test_judgment_agents_pinned_to_opus(self):
        for name in OPUS_AGENTS:
            with self.subTest(agent=name):
                self.assertEqual(_agent_model(name), "opus")

    def test_no_agent_pins_1m_context(self):
        # The whole point of pinning opus is to shed the [1m] 1M-context beta;
        # no agent's model field may carry it.
        for name in SONNET_AGENTS + OPUS_AGENTS:
            with self.subTest(agent=name):
                self.assertNotIn("[1m]", _agent_model(name))


if __name__ == "__main__":
    unittest.main()
