#!/usr/bin/env python3
"""Which `close_started` anchors the reviewer-completion evidence scan.

The evidence release asks "did the close-reviewer complete AFTER the close that
armed this gate started". It anchored on the LATEST `close_started` in the log,
whatever mode wrote it. Only three close modes arm the gate; the fourth
(story) emits `close_started` too, so the lead's own next story-close moves the
anchor past the evidence — no second session needed.

The cost is a FALSE high-severity concern, and it is the one the release guard
exists to prevent: the reviewer completes, the marker consume is lost (the
crash case), a story-close appends its own `close_started`, the scan then finds
no completion after it, and once the marker ages out the bypass records "close
abandoned, the reviewer never ran" against a close whose reviewer demonstrably
ran — which then counts against the next close's merge gate.

See test_close_cycle_stop_gate_deferral.py for the release itself and
test_close_cycle_stop_gate_core.py for why story-close does not arm the gate.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import close_cycle_stop_gate
import markers
from conftest import _HookTestCase, _make_stop_input, make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS


class _AnchorTestCase(_HookTestCase):
    def seed_close_started(self, close_mode: str | None) -> None:
        """A close preload's `close_started`. None omits close_mode entirely —
        the shape of an event written before the field existed."""
        metadata: dict = {"action": "close_started"}
        if close_mode is not None:
            metadata["close_mode"] = close_mode
        self._seed(metadata)

    def seed_reviewer_completion(self) -> None:
        self._seed({"action": "subagent_complete", "agent_type": "xp-close-reviewer"})

    def _seed(self, metadata: dict) -> None:
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_STATUS,
                agent_id="seed",
                content=f"seed {metadata['action']}",
                working_on=[],
                metadata=metadata,
            ),
        )

    def arm(self) -> Path:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        return markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)

    def age_out(self, marker_path: Path) -> None:
        backdate = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
        old = marker_path.stat().st_mtime - backdate
        os.utime(marker_path, (old, old))

    def concerns(self) -> list[dict]:
        return [e for e in self._read_events() if e.get("type") == EVENT_TYPE_CONCERN]


class TestNonArmingModeDoesNotMoveTheAnchor(_AnchorTestCase):
    def test_a_later_story_close_does_not_hide_the_evidence(self):
        self.arm()
        self.seed_close_started("sprint")
        self.seed_reviewer_completion()
        self.seed_close_started("story")

        self.assertTrue(
            close_cycle_stop_gate.reviewer_completed_this_cycle(self.smm_dir)
        )
        self.assertIsNone(
            close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        )

    def test_no_false_abandonment_concern_after_a_story_close(self):
        """The harm, end to end: aged marker + stop_hook_active must not record
        an abandonment concern when a reviewer did run this cycle."""
        marker_path = self.arm()
        self.seed_close_started("free")
        self.seed_reviewer_completion()
        self.seed_close_started("story")
        self.age_out(marker_path)

        result = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)
        self.assertEqual(self.concerns(), [])

    def test_a_story_anchor_alone_releases_nothing(self):
        """The scan must not release just because the only close_started came
        from a mode it skips — no anchor means no evidence."""
        self.arm()
        self.seed_reviewer_completion()
        self.seed_close_started("story")

        self.assertFalse(
            close_cycle_stop_gate.reviewer_completed_this_cycle(self.smm_dir)
        )


class TestUnlabelledAnchorStillCounts(_AnchorTestCase):
    """Fail CLOSED on an anchor whose mode is unknown: it still bounds the
    scan, so a prior cycle's completion cannot release this one. Skipping it
    would move the anchor BACKWARD, which only makes a release likelier."""

    def test_close_started_without_a_mode_still_anchors(self):
        self.arm()
        self.seed_reviewer_completion()
        self.seed_close_started(None)

        self.assertFalse(
            close_cycle_stop_gate.reviewer_completed_this_cycle(self.smm_dir)
        )

    def test_completion_after_an_unlabelled_anchor_releases(self):
        self.arm()
        self.seed_close_started(None)
        self.seed_reviewer_completion()

        self.assertTrue(
            close_cycle_stop_gate.reviewer_completed_this_cycle(self.smm_dir)
        )


if __name__ == "__main__":
    unittest.main()
