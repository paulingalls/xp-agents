#!/usr/bin/env python3
"""Capstone smoke test for the deterministic-event-emission doctrine (M3):
per-constant emission checks.

Split from test_action_vocabulary_smoke.py (was 513 lines) when it crossed
the 500-line cap. This half runs each driver in ``_PRODUCER_CASES`` (defined
in _action_vocabulary_smoke_helpers.py) against a fresh SMM and
confirms at least one emitted event carries ``metadata.action`` set to the
constant's value, plus a hand-pinned check for the
``STATUS_ACTION_SPRINT_RETRO_DONE`` / ``RETRO_ACTION_SPRINT_DONE`` pair the
canary cannot see. The missing-coverage canary itself lives in
test_action_vocabulary_smoke_coverage.py.

**Per-constant emission** — each driver runs and at least one event
carries the expected ``metadata.action``. Stubs returning ``[]`` fail
this assertion until the producer is wired.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import event_schema
from _action_vocabulary_smoke_helpers import (
    _PRODUCER_CASES,
    _drive_sprint_retro_done,
)
from conftest import _HookTestCase
from event_schema import event_action


class TestActionVocabularySmoke(_HookTestCase):
    """Capstone: every STATUS_ACTION_* must be exercised by a driver."""

    def _reset_smm(self) -> None:
        """Wipe smm_dir back to the setUp baseline (events.jsonl + lock).

        Per-subTest reset prevents marker leakage across drivers — e.g.
        ``_drive_close_started`` writes a close marker and review-cycle
        drivers write a review flag. Without this reset, a later driver's
        behavior would depend on dict-iteration order of ``_PRODUCER_CASES``.
        """
        for child in self.smm_dir.iterdir():
            if child.name == "events.lock":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.events_file.touch()

    def test_per_constant_action_emitted(self):
        """Each driver emits at least one event with metadata.action = value."""
        for name, driver in _PRODUCER_CASES.items():
            with self.subTest(action=name):
                action_value = getattr(event_schema, name)
                self._reset_smm()
                events = driver(self.smm_dir)
                actions = [event_action(e) for e in events]
                self.assertIn(
                    action_value,
                    actions,
                    f"driver for {name} emitted no event with "
                    f"metadata.action={action_value!r}; actions seen: {actions!r}",
                )

    def test_sprint_retro_done_is_a_status_event_carrying_its_sprint_id(self):
        """The canary above CANNOT see this one, so it is pinned by hand.

        `event_schema` declares TWO constants with the identical value
        `sprint_retro_done` on DIFFERENT event types — STATUS_ACTION_SPRINT_RETRO_DONE
        (status) and RETRO_ACTION_SPRINT_DONE (retrospective). The canary matches on
        `metadata.action` alone, so the long-standing retrospective-type event
        satisfies it VACUOUSLY: the driver goes green whether or not the status
        producer exists at all. It did exactly that before this test was written.

        What the consumers actually require is the pair — type `status` AND a
        `sprint_id` — because that is what releases a sprint's commit events from
        compaction's retention (`compact_retention._compute_pending_retro_sprint_ids`)
        and what stops `needs_sprint_retro` re-firing. Emitting the action on the
        wrong type, or on the right type with no sprint_id, misses on either count
        and pins the sprint's commits forever. That was debt ef03cbc32f1e.

        The retrospective-type event must SURVIVE: retro tooling reads its action to
        tell a sprint retro from a session retro. This is an ADDED event, not a
        retyped one.
        """
        self._reset_smm()
        events = _drive_sprint_retro_done(self.smm_dir)

        markers = [
            e
            for e in events
            if e.get("type") == event_schema.EVENT_TYPE_STATUS
            and event_action(e) == event_schema.STATUS_ACTION_SPRINT_RETRO_DONE
        ]
        self.assertEqual(
            len(markers),
            1,
            "exactly one status-type sprint_retro_done marker must be emitted; "
            f"saw {len(markers)}",
        )
        self.assertEqual(
            markers[0]["metadata"].get("sprint_id"),
            "sprint-001",
            "the marker must name the sprint from the sprint_end event in the LOG "
            "— sprint.json may already have rolled over, and a wrong id would "
            "release the WRONG sprint's commits",
        )

        retros = [
            e
            for e in events
            if e.get("type") == event_schema.EVENT_TYPE_RETROSPECTIVE
            and event_action(e) == event_schema.RETRO_ACTION_SPRINT_DONE
        ]
        self.assertEqual(
            len(retros),
            1,
            "the retrospective-type event must still be written — retro tooling "
            "reads its action to tell a sprint retro from a session retro",
        )


if __name__ == "__main__":
    unittest.main()
