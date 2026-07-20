#!/usr/bin/env python3
"""Tests for work_selection_decide.py — the FORCE-CLOSE gate's core behavior
plus the pure filter functions it's built from.

FORCE-CLOSE: refuse plain defer when a Try has been deferred 3+ times.
Carrying a Try across 3+ retros without adoption is dishonest. Gate fires on
the 4th defer attempt; user must use a force flag.

Split from test_work_selection_decide.py to stay under the file-size budget.
Extended coverage (mixed-history reconciliation, compaction survival, lane
scoping, CLI) lives in test_work_selection_decide_force_close_extra.py.
Shared base TestCases live in _work_selection_decide_helpers.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import work_selection_decide
from _work_selection_decide_helpers import _RETRO_DEFERRED, _ForceCloseTestCase
from conftest import make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)


class TestForceCloseGate(_ForceCloseTestCase):
    """Plain defer is allowed up to 2 prior defers, refused at 3+."""

    def test_zero_prior_defers_allowed(self):
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer this [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_two_prior_defers_allowed(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 2)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer again [refs: aaaaaaaaaaaa]",
        )
        # Last event is the new defer; the seeded 2 still precede.
        self.assertEqual(len(self._read_events()), 3)
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")

    def test_three_prior_defers_plain_defer_refused(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Defer once more [refs: aaaaaaaaaaaa]",
            )
        msg = str(ctx.exception)
        self.assertIn("FORCE-CLOSE", msg)
        # The Try id is named so the user can find the offending item.
        self.assertIn("aaaaaaaa", msg)
        # No new event was written.
        self.assertEqual(len(self._read_events()), 3)

    def test_four_prior_defers_plain_defer_refused(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 4)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="And again [refs: aaaaaaaaaaaa]",
            )

    def test_no_refs_skips_gate(self):
        """No refs means nothing to count — defer always allowed."""
        # Seed unrelated history; without refs in content, gate can't link.
        self._seed_prior_defers("aaaaaaaaaaaa", 5)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Defer with no refs",
        )
        self.assertEqual(self._last_event()["metadata"], _RETRO_DEFERRED)

    def test_defers_for_other_try_dont_count(self):
        """Only defers whose resolves overlap with the current refs count."""
        self._seed_prior_defers("bbbbbbbbbbbb", 5)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Different Try [refs: aaaaaaaaaaaa]",
        )
        self.assertEqual(self._last_event()["metadata"]["disposition"], "deferred")


class TestForceAdoptBreaksGate(_ForceCloseTestCase):
    """--force-adopt converts the gated defer into an adopt decision."""

    def test_force_adopt_at_threshold_writes_decision(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Adopt now [refs: aaaaaaaaaaaa]",
            force_adopt_topic="retro-try-finally-adopted",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_DECISION)
        self.assertEqual(event["topic"], "retro-try-finally-adopted")
        # Forced or not, an adoption is still intent — it links, it doesn't close.
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])
        self.assertNotIn("resolves", event.get("metadata", {}))
        self.assertEqual(event["content"], "Adopt now")


class TestForceDropBreaksGate(_ForceCloseTestCase):
    """--force-drop converts the gated defer into a drop status."""

    def test_force_drop_at_threshold_writes_dropped(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Drop forever [refs: aaaaaaaaaaaa]",
            force_drop=True,
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "dropped")
        self.assertEqual(event["metadata"]["resolves"], ["aaaaaaaaaaaa"])


class TestForceDeferWithDateBreaksGate(_ForceCloseTestCase):
    """--force-defer-with-date defers but records a target date in metadata."""

    def test_force_defer_with_date_writes_defer_until(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self.mod.run(
            action="defer",
            smm_dir=self.smm_dir,
            content="Hold until [refs: aaaaaaaaaaaa]",
            force_defer_until="2026-09-01",
        )
        event = self._last_event()
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertEqual(event["metadata"]["disposition"], "deferred")
        self.assertEqual(event["metadata"]["defer_until"], "2026-09-01")
        self.assertEqual(event["references"], ["aaaaaaaaaaaa"])
        self.assertNotIn("resolves", event["metadata"])

    def test_force_defer_with_date_rejects_bad_date_format(self):
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError):
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Hold until [refs: aaaaaaaaaaaa]",
                force_defer_until="next quarter",
            )

    def test_force_defer_with_date_rejects_past_date(self):
        """Past dates would silently launder Tries past the FORCE-CLOSE gate."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Hold until [refs: aaaaaaaaaaaa]",
                force_defer_until="2020-01-01",
            )
        self.assertIn("today", str(ctx.exception))
        self.assertIn("launder", str(ctx.exception))

    def test_force_close_message_lists_all_refs(self):
        """Multi-ref Tries: message names every gated ref, not just the first."""
        self._seed_prior_defers("aaaaaaaaaaaa", 3)
        self._seed_prior_defers("bbbbbbbbbbbb", 3)
        with self.assertRaises(ValueError) as ctx:
            self.mod.run(
                action="defer",
                smm_dir=self.smm_dir,
                content="Both stale [refs: aaaaaaaaaaaa, bbbbbbbbbbbb]",
            )
        msg = str(ctx.exception)
        self.assertIn("aaaaaaaa", msg)
        self.assertIn("bbbbbbbb", msg)


class _ReferencesHistoryMixin:
    """Re-run a FORCE-CLOSE suite against deferral history recorded the NEW
    way (top-level `references`) instead of the legacy metadata.resolves.

    Subclassing rather than parameterizing: this file runs under plain
    `unittest discover` in CI, where a pytest marker would deselect nothing
    and break the run (decision `test-runner-portability`).
    """

    def _seed_prior_defers(
        self, try_ref_id: str, count: int, link_field: str = "references"
    ) -> None:
        super()._seed_prior_defers(try_ref_id, count, link_field)  # type: ignore[misc]


class TestForceCloseGateReferencesHistory(_ReferencesHistoryMixin, TestForceCloseGate):
    """The gate counts deferrals linked via `references`, not just resolves."""


class TestForceAdoptBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceAdoptBreaksGate
):
    pass


class TestForceDropBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceDropBreaksGate
):
    pass


class TestForceDeferWithDateBreaksGateReferencesHistory(
    _ReferencesHistoryMixin, TestForceDeferWithDateBreaksGate
):
    pass


class TestForceDropFilterFunctions(unittest.TestCase):
    """Pure filter functions over an event list — no SMM I/O, no flock.

    The force-drop path used to do 3 independent locked reads
    (_convention_topic_exists, _count_prior_defers, _build_drop_event
    cascade). Filters now take the events list as an arg so they can be
    unit-tested without writing to disk, and the orchestrator does one
    locked read per invocation.
    """

    def _events(self) -> list[dict]:
        # Mixed event set: 2 conventions, 2 deferred statuses, 1 debt, 1 concern.
        return [
            make_event(
                EVENT_TYPE_CONVENTION,
                topic="retro-drop-foo",
                content="durable suppression for foo",
            ),
            make_event(
                EVENT_TYPE_CONVENTION,
                topic="retro-drop-bar",
                content="durable suppression for bar",
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try ref aaaaaaaaaaaa",
                metadata={"disposition": "deferred", "resolves": ["aaaaaaaaaaaa"]},
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try ref bbbbbbbbbbbb",
                metadata={"disposition": "deferred", "resolves": ["bbbbbbbbbbbb"]},
            ),
            make_event(EVENT_TYPE_DEBT, content="some debt", files=["x.py"]),
            make_event(EVENT_TYPE_CONCERN, content="some concern", files=["y.py"]),
        ]

    def test_convention_topic_exists_filter_hit(self):
        self.assertTrue(
            work_selection_decide._convention_topic_exists_filter(
                self._events(), "retro-drop-foo"
            )
        )

    def test_convention_topic_exists_filter_miss(self):
        self.assertFalse(
            work_selection_decide._convention_topic_exists_filter(
                self._events(), "retro-drop-unseen"
            )
        )

    def test_count_prior_defers_filter_counts_matches(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(
                self._events(), ["aaaaaaaaaaaa"]
            ),
            1,
        )

    def test_count_prior_defers_filter_counts_references_link(self):
        """New-shape deferrals name their Try in `references`."""
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try",
                metadata={"disposition": "deferred"},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            1,
        )

    def test_count_prior_defers_filter_counts_double_linked_event_once(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="deferred Try",
                metadata={"disposition": "deferred", "resolves": ["cccccccccccc"]},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            1,
        )

    def test_count_prior_defers_filter_ignores_non_deferred_references(self):
        """An adopting status also carries `references` now — it is not a defer."""
        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="adopted Try",
                metadata={"disposition": "adopted"},
                references=["cccccccccccc"],
            )
        ]
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(events, ["cccccccccccc"]),
            0,
        )

    def test_count_prior_defers_filter_handles_empty_refs(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(self._events(), []),
            0,
        )

    def test_count_prior_defers_filter_no_match(self):
        self.assertEqual(
            work_selection_decide._count_prior_defers_filter(
                self._events(), ["ffffffffffff"]
            ),
            0,
        )

    def test_cascade_ids_filter_returns_resolvable_overlap(self):
        events = self._events()
        debt_id = events[4]["id"]
        concern_id = events[5]["id"]
        result = work_selection_decide._cascade_ids_filter(
            events, {debt_id, concern_id, "no-such-id"}
        )
        self.assertEqual(result, {debt_id, concern_id})

    def test_cascade_ids_filter_skips_non_resolvable_types(self):
        # CONVENTION + STATUS events are not in PROBE_RESOLVABLE_TYPES,
        # so even if their ids appear in tokens they must not cascade-close.
        events = self._events()
        convention_id = events[0]["id"]
        status_id = events[2]["id"]
        result = work_selection_decide._cascade_ids_filter(
            events, {convention_id, status_id}
        )
        self.assertEqual(result, set())


if __name__ == "__main__":
    unittest.main()
