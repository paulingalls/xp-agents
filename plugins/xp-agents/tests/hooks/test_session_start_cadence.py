#!/usr/bin/env python3
"""Tests for session_start.py: session-scoped review-cadence staleness reset.

story-003. session_start owns the cadence staleness guarantee: a fresh start
(startup/clear) resets the cadence to the careful 'commit' default; resume and
compact (mid-session continuations) preserve the active cadence.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import session_start
from conftest import _HookTestCase, make_event


class TestSessionStartCadence(_HookTestCase):
    """story-003: fresh-start resets cadence; resume/compact preserve it."""

    def _run(self, source: str) -> None:
        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": source}, smm_dir=self.smm_dir
        )

    def test_fresh_start_resets_to_commit(self):
        """AC#1: startup/clear reset a stale 'story' cadence to 'commit'."""
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                markers.write_review_cadence(self.smm_dir, "story")
                self._run(source)
                self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")

    def test_continuation_preserves_cadence(self):
        """AC#2: resume/compact preserve the active 'story' cadence."""
        for source in ("resume", "compact"):
            with self.subTest(source=source):
                markers.write_review_cadence(self.smm_dir, "story")
                self._run(source)
                self.assertEqual(markers.read_review_cadence(self.smm_dir), "story")

    def test_e2e_prior_story_resets_on_new_session(self):
        """AC#3 E2E: a prior session's 'story' cadence reverts to 'commit'."""
        markers.write_review_cadence(self.smm_dir, "story")  # prior session
        self._run("startup")  # new fresh session
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")


if __name__ == "__main__":
    unittest.main()
