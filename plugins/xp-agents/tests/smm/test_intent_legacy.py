#!/usr/bin/env python3
"""Tests for smm/intent.py — the INTENT link (adopted / deferred).

The link `intent.py` reads is deliberately narrow, because the obvious wide rule
is wrong twice and each way is pinned here:

  * "id appears in `references` ⇒ intent" over-matches. Events reference ids for
    reasons that are the OPPOSITE of adoption — the auto-raised "stale question"
    concern names the question it is complaining about. `TestReferenceIsNotIntent`.
  * "an adopting event's reference bag is a list of adoption targets" is false.
    A Try's `[refs: ...]` bag carries the Try id PLUS the debt/concern ids the
    Try is merely ABOUT. `TestCitedIdIsNotAdopted` — the headline regression.

Fixtures come from the REAL writer (`conftest.adopt_try_event` and friends), so
a test cannot pass against a shape the writer does not produce.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _intent_helpers import TRY_ID, _IntentTestCase
from conftest import make_event, make_retrospective_with_try

# Explicit imports so a future constant rename fails at collection.
from event_schema import (
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)


class TestLegacyEvents(_IntentTestCase):
    """Events already on disk carry no lane tag. Without a legacy leg they are
    re-proposed at the next kickoff, forever — which is the bug, restored."""

    def test_legacy_retro_adopt_decision_reads_adopted(self):
        """4 such events exist: a `decision` with a retro-try-<slug> topic and
        no metadata.action."""
        retro = make_retrospective_with_try(TRY_ID)
        legacy = make_event(
            EVENT_TYPE_DECISION,
            content="Adopt the Try",
            topic="retro-try-run-tests-first",
            references=[TRY_ID],
        )
        entry = self._retro_map([retro, legacy])[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)

    def test_legacy_retro_adopt_still_respects_the_try_id_scope(self):
        """The legacy leg is not an escape hatch from the bag rule."""
        retro = make_retrospective_with_try(TRY_ID)
        debt = make_event(EVENT_TYPE_DEBT, content="Cited debt")
        legacy = make_event(
            EVENT_TYPE_DECISION,
            content="Adopt the Try",
            topic="retro-try-run-tests-first",
            references=[TRY_ID, debt["id"]],
        )
        self.assertNotIn(debt["id"], self._retro_map([retro, debt, legacy]))

    def test_a_decision_without_the_retro_topic_is_not_a_legacy_adoption(self):
        retro = make_retrospective_with_try(TRY_ID)
        unrelated = make_event(
            EVENT_TYPE_DECISION,
            content="Some architectural call that happens to cite the Try",
            topic="use-typed-errors",
            references=[TRY_ID],
        )
        self.assertEqual(self._retro_map([retro, unrelated]), {})

    def test_legacy_triage_adopt_status_reads_adopted(self):
        """A `status` + disposition=adopted + no action is necessarily a triage
        adopt — the retro lane's adopt is a `decision`."""
        debt = make_event(EVENT_TYPE_DEBT, content="Legacy-adopted debt")
        legacy = make_event(
            EVENT_TYPE_STATUS,
            content=f"Triage: adopted {debt['id'][:8]}",
            working_on=[],
            references=[debt["id"]],
            metadata={"disposition": DISPOSITION_ADOPTED},
        )
        entry = self._triage_map([debt, legacy])[debt["id"]]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)

    def test_legacy_retro_defer_status_reads_deferred(self):
        """A retro deferral written before the lane tag: an untagged `status`,
        disposition=deferred, naming its Try in `references`. It IS recoverable
        — the link is right there — and the FORCE-CLOSE gate already counts
        exactly this event (`_counts_as_retro_defer`'s untagged leg). Ignoring
        it here would let one commit read one event two ways, and would re-offer
        a long-carried Try with no memory that it was ever carried.
        """
        retro = make_retrospective_with_try(TRY_ID)
        legacy = make_event(
            EVENT_TYPE_STATUS,
            content="Carry the Try",
            working_on=[],
            references=[TRY_ID],
            metadata={"disposition": DISPOSITION_DEFERRED},
        )
        entry = self._retro_map([retro, legacy])[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_DEFERRED)
        self.assertEqual(entry["defer_count"], 1)

    def test_legacy_retro_defer_cannot_leak_a_cited_debt(self):
        """The `∩ try_ids` scope is what makes the leg above safe: an untagged
        deferral's bag holds the cited debt ids too, and a legacy triage-defer
        (which links NOTHING) can never name a Try id, so it cannot arrive here.
        """
        retro = make_retrospective_with_try(TRY_ID)
        debt = make_event(EVENT_TYPE_DEBT, content="Cited debt")
        legacy = make_event(
            EVENT_TYPE_STATUS,
            content="Carry the Try",
            working_on=[],
            references=[TRY_ID, debt["id"]],
            metadata={"disposition": DISPOSITION_DEFERRED},
        )
        events = [retro, debt, legacy]
        self.assertNotIn(debt["id"], self._retro_map(events))
        self.assertNotIn(debt["id"], self._triage_map(events))

    def test_legacy_triage_defer_is_unrecoverable(self):
        """~20 of these exist and they link NOTHING — there is no id on the
        event to recover. Pinned so the gap is a stated fact, not a surprise:
        the item is simply re-offered, which is the pre-story behaviour.
        """
        debt = make_event(EVENT_TYPE_DEBT, content="Legacy-deferred debt")
        legacy = make_event(
            EVENT_TYPE_STATUS,
            content=f"Triage: deferred {debt['id'][:8]}",
            working_on=[],
            metadata={"disposition": DISPOSITION_DEFERRED},
        )
        self.assertEqual(self._triage_map([debt, legacy]), {})


if __name__ == "__main__":
    unittest.main()
