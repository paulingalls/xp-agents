#!/usr/bin/env python3
"""Pin: flag-style concerns wire `references=[root_id]` and cascade-close.

Story-009 (sprint-065 burndown). Carries forward sprint-063 retro Try-2:
flag-style concerns (divert/escape/stale/superseded/convention-violation)
emitted by retros and reviewers must attach `references=[root_id]` so the
WEAK cascade in `smm/resolution.py` closes them when the root resolves.

Two assertions:

(a) Frontmatter-aware grep — each of the 5 agent .md files (4 reviewers +
    retrospective) contains a normative phrase pairing "flag" with the
    literal `references=[root_id]`. The body is checked, not the
    frontmatter — per constraint b769cb0cabaa, frontmatter literals can
    false-pass `assertIn` if the body silently regresses.

(b) E2E cascade — appending a root concern, a flag concern with
    `references=[root_id]`, and a status event with `metadata.resolves`
    closes BOTH concerns via `compute_resolutions`. Pins that the
    resolution machinery already does the cascade work; this story only
    teaches the agents to wire the link.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    _SMMTestCase,
    _split_frontmatter_body,
    compute_resolutions,
    make_event,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_AGENT_FILES = [
    _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md",
    _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md",
    _PLUGIN_ROOT / "agents" / "xp-sprint-reviewer.md",
    _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md",
    _PLUGIN_ROOT / "agents" / "xp-retrospective.md",
]


class TestAgentsPinFlagCascadeGuidance(unittest.TestCase):
    """Each agent .md body MUST guide flag-style concerns to wire references."""

    def test_each_agent_body_contains_flag_cascade_guidance(self):
        for path in _AGENT_FILES:
            with self.subTest(agent=path.name):
                self.assertTrue(path.is_file(), f"missing agent file: {path}")
                _, body = _split_frontmatter_body(path.read_text())
                # Pair "flag" with the literal `references=[root_id]` token
                # within the same body (not the frontmatter). The pairing is
                # what makes it normative — a stray mention of either alone
                # would not direct an agent to wire the cascade link.
                self.assertIn(
                    "references=[root_id]",
                    body,
                    f"{path.name}: body lacks the literal "
                    "`references=[root_id]` token that pins the cascade link",
                )
                self.assertRegex(
                    body,
                    r"(?i)flag[- ](style )?concern",
                    f"{path.name}: body lacks a 'flag(-style) concern' phrase "
                    "near the cascade-link guidance",
                )


class TestFlagConcernCascadeCloses(_SMMTestCase):
    """E2E: a flag concern with `references=[root_id]` cascade-closes.

    Uses `_SMMTestCase` (not `_IntegrationTestCase`) — this test only needs
    a temp SMM dir for `_write_events` / `_read_events`; it does not invoke
    a hook subprocess or touch a git repo. The lighter base saves ~5 git
    + init.sh subprocess calls per pre-commit pytest run.
    """

    def test_flag_concern_resolves_when_root_concern_resolves(self):
        root = make_event(
            EVENT_TYPE_CONCERN,
            agent_id="xp-retrospective",
            content="Stop hook drifts from spec",
            severity="medium",
            files=["plugins/xp-agents/scripts/post_tool_use.py"],
        )
        flag = make_event(
            EVENT_TYPE_CONCERN,
            agent_id="xp-retrospective",
            content="divert: superseded by stop-hook rewrite",
            severity="low",
            references=[root["id"]],
        )
        # Status event resolves the root via metadata.resolves — the
        # standard wiring used by the auto-resolve helpers.
        resolver = make_event(
            EVENT_TYPE_STATUS,
            agent_id="main",
            content="resolved: stop hook fixed",
            metadata={"resolves": [root["id"]]},
            working_on=[],
        )

        self._write_events([root, flag, resolver])
        events = self._read_events()

        resolutions = compute_resolutions(events)
        resolved_ids = resolutions["resolved_concern_ids"]

        self.assertIn(
            root["id"],
            resolved_ids,
            "root concern should resolve via metadata.resolves",
        )
        self.assertIn(
            flag["id"],
            resolved_ids,
            "flag concern should cascade-close via references=[root_id]",
        )


if __name__ == "__main__":
    unittest.main()
