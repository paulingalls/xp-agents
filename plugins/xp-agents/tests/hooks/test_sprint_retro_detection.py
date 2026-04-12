#!/usr/bin/env python3
"""Tests for sprint_retro_detection.needs_sprint_retro.

Decides whether the next session start should run a sprint retro
(because the previous session ended a sprint without retrospecting it)
instead of the regular session retro.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event


def _sprint_start(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} started",
        metadata={"sprint_id": sprint_id, "action": "start"},
    )


def _sprint_end(sprint_id: str) -> dict:
    return make_event(
        "sprint",
        content=f"Sprint {sprint_id} ended",
        metadata={"sprint_id": sprint_id, "action": "end"},
    )


def _sprint_retro_done(sprint_id: str) -> dict:
    return make_event(
        "status",
        content="Sprint retrospective complete.",
        metadata={"sprint_id": sprint_id, "action": "sprint_retro_done"},
    )


class TestNeedsSprintRetro(_HookTestCase):
    """needs_sprint_retro(events) returns sprint_id or None."""

    def test_dangling_sprint_end_returns_sprint_id(self):
        """Sprint ended with no matching retro_done: sprint retro is needed."""
        import sprint_retro_detection

        events = [
            _sprint_start("s-001"),
            make_event(content="work during sprint"),
            _sprint_end("s-001"),
            make_event(content="post-sprint activity"),
        ]
        self.assertEqual(sprint_retro_detection.needs_sprint_retro(events), "s-001")

    def test_sprint_end_with_matching_retro_done_returns_none(self):
        """Sprint ended and retro already done for that sprint_id: no retro needed."""
        import sprint_retro_detection

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            make_event(content="post-retro activity"),
        ]
        self.assertIsNone(sprint_retro_detection.needs_sprint_retro(events))

    def test_no_sprint_end_returns_none(self):
        """No sprint_end event exists: no sprint retro needed."""
        import sprint_retro_detection

        events = [
            _sprint_start("s-001"),
            make_event(content="mid-sprint work"),
        ]
        self.assertIsNone(sprint_retro_detection.needs_sprint_retro(events))

    def test_empty_events_returns_none(self):
        """Empty event log: no sprint retro needed."""
        import sprint_retro_detection

        self.assertIsNone(sprint_retro_detection.needs_sprint_retro([]))

    def test_abandoned_sprint_returns_none(self):
        """Sprint ended, then a NEWER sprint started without retro for the old
        one. User has taken manual control — let the session retro handle it."""
        import sprint_retro_detection

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            # No retro_done for s-001.
            _sprint_start("s-002"),
            make_event(content="new sprint work"),
        ]
        self.assertIsNone(sprint_retro_detection.needs_sprint_retro(events))

    def test_stale_retro_done_different_sprint_id_returns_sprint_id(self):
        """sprint_retro_done for a previous sprint does not satisfy detection
        for the most recent sprint_end."""
        import sprint_retro_detection

        events = [
            _sprint_start("s-001"),
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_start("s-002"),
            _sprint_end("s-002"),
            # No retro_done for s-002.
        ]
        self.assertEqual(sprint_retro_detection.needs_sprint_retro(events), "s-002")

    def test_most_recent_sprint_end_is_the_one_checked(self):
        """When multiple sprint_ends exist, only the most recent one's
        sprint_id matters for detection."""
        import sprint_retro_detection

        events = [
            _sprint_end("s-001"),
            _sprint_retro_done("s-001"),
            _sprint_end("s-002"),
            _sprint_retro_done("s-002"),
            _sprint_end("s-003"),
            # s-003 not retro'd yet.
        ]
        self.assertEqual(sprint_retro_detection.needs_sprint_retro(events), "s-003")


if __name__ == "__main__":
    unittest.main()
