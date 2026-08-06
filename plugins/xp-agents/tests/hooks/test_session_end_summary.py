#!/usr/bin/env python3
"""session_end's summary — the working_on aggregation.

Split from test_session_lifecycle.py, which was at its recorded band ceiling.
The aggregation reads the LATEST status per agent over the WHOLE log with no
session fence, so which claims count is its own question, separate from the
duration/unresolved/goal-resolution behaviours that file covers.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import _HookTestCase, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_SESSION_END, EVENT_TYPE_STATUS

_WATERMARK_ID = "test-session-end-summary"


class TestWorkingOnSummary(_HookTestCase):
    def _summary(self) -> dict:
        import session_end

        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return events_of_type(events, EVENT_TYPE_SESSION_END)[0]

    def test_active_working_on(self):
        self._write_events(
            [make_event(EVENT_TYPE_STATUS, agent_id="main", working_on=["src/app.ts"])]
        )
        self.assertIn("src/app.ts", self._summary()["working_on"])

    def test_plugin_subagent_claims_are_not_reported_as_in_flight(self):
        """A plugin subagent's claim is never cleared, so it is never stale.

        The map keeps the latest status per agent id across the whole log, so
        an `xp-` claim from a subagent that finished sessions ago stays the
        latest one for that id — and gets reported as work in flight in every
        summary from then on. The conflict detector and the subagent dispatcher
        already fence on the `xp-` prefix; this reader is the one that did not,
        and the fence has to hold without swallowing the real claims beside it.
        """
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_STATUS, agent_id="xp-plan", working_on=["plan.json"]
                ),
                make_event(
                    EVENT_TYPE_STATUS, agent_id="main", working_on=["src/app.ts"]
                ),
            ]
        )
        summary = self._summary()
        self.assertNotIn("plan.json", summary["working_on"])
        self.assertIn("src/app.ts", summary["working_on"])

    def test_a_teammate_claim_is_still_reported(self):
        """The fence must not swallow a CLI teammate, whose id is not xp-*."""
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_STATUS,
                    agent_id="worktree-story-002",
                    working_on=["src/other.ts"],
                )
            ]
        )
        self.assertIn("src/other.ts", self._summary()["working_on"])


if __name__ == "__main__":
    unittest.main()
