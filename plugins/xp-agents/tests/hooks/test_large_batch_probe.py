#!/usr/bin/env python3
"""Tests for large_batch_probe — checkpoint-nudge probe.

Reframes the carry-forward checkpoint Try as tooling: when the main
agent has emitted >40 events since its last commit, append a status
nudge advising an intermediate green-state commit.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import large_batch_probe as lbp
from conftest import _HookTestCase, _make_bash_input, commit_event, make_event
from event_schema import EVENT_TYPE_STATUS


def _seed_status_events(count: int, agent_id: str = "main") -> list[dict]:
    return [
        make_event(EVENT_TYPE_STATUS, agent_id=agent_id, content=f"status {i}")
        for i in range(count)
    ]


class TestLargeBatchProbe(_HookTestCase):
    def _nudges(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("agent_id") == lbp.NUDGE_AGENT_ID
            and e.get("type") == EVENT_TYPE_STATUS
        ]

    def test_nudge_fires_above_threshold(self):
        self._write_events(_seed_status_events(41))
        result = lbp.run(_make_bash_input(), smm_dir=self.smm_dir)
        # Returned text is what surfaces to the agent via additionalContext;
        # the status event is the parallel SMM record.
        self.assertEqual(result, lbp.NUDGE_CONTENT)
        nudges = self._nudges()
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0]["content"], lbp.NUDGE_CONTENT)

    def test_no_nudge_for_non_main_agent(self):
        self._write_events(_seed_status_events(100, agent_id="worktree-story-001"))
        result = lbp.run(
            _make_bash_input(agent_id="worktree-story-001"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertEqual(self._nudges(), [])

    def test_no_nudge_for_xp_subagent(self):
        # Recursion guard: an xp- subagent's tool calls must not trigger.
        self._write_events(_seed_status_events(100))
        result = lbp.run(
            _make_bash_input(agent_type="xp-retrospective"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertEqual(self._nudges(), [])

    def test_no_nudge_at_boundary(self):
        self._write_events(_seed_status_events(40))
        result = lbp.run(_make_bash_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertEqual(self._nudges(), [])

    def test_no_duplicate_nudge_in_batch_window(self):
        existing = make_event(
            EVENT_TYPE_STATUS,
            agent_id=lbp.NUDGE_AGENT_ID,
            content=lbp.NUDGE_CONTENT,
            working_on=[],
        )
        self._write_events([*_seed_status_events(41), existing])
        result = lbp.run(_make_bash_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertEqual(len(self._nudges()), 1)

    def test_main_commit_resets_window(self):
        """Events before the most recent main-agent commit don't count."""
        seed = [*_seed_status_events(41), commit_event(["src/foo.py"])]
        self._write_events(seed)
        result = lbp.run(_make_bash_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertEqual(self._nudges(), [])


if __name__ == "__main__":
    unittest.main()
