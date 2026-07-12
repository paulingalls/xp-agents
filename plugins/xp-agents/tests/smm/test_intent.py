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

import intent
import resolution
from conftest import (
    _SMMTestCase,
    adopt_try_event,
    defer_try_event,
    drop_try_event,
    make_event,
    make_retrospective_with_try,
    triage_event,
)

# Explicit imports so a future constant rename fails at collection.
from event_schema import (
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)

TRY_ID = "aa11bb22cc33"
DEBT_ID = "dd44ee55ff66"


class _IntentTestCase(_SMMTestCase):
    """Adds the two map builders with the try-id scope wired the way production
    wires it, so no test can accidentally hand-pick a friendlier scope."""

    def _retro_map(self, events: list[dict]) -> dict:
        return intent.build_retro_intent_map(events, intent.retro_try_ids(events))

    def _triage_map(self, events: list[dict]) -> dict:
        return intent.build_triage_intent_map(events)


class TestRetroTryIds(_IntentTestCase):
    """retro_try_ids finds the nested try[] ids, and nothing else."""

    def test_finds_nested_try_ids(self):
        events = [make_retrospective_with_try(TRY_ID)]
        self.assertEqual(intent.retro_try_ids(events), {TRY_ID})

    def test_top_level_event_ids_are_not_try_ids(self):
        debt = make_event(EVENT_TYPE_DEBT, content="A debt", id=DEBT_ID)
        events = [make_retrospective_with_try(TRY_ID), debt]
        self.assertEqual(intent.retro_try_ids(events), {TRY_ID})


class TestAdoptIsIntentNotClosure(_IntentTestCase):
    """AC1: an adopted Try reports intent=adopted AND stays UNRESOLVED.

    Both halves, in one test: linking is not closing. If adoption ever starts
    closing its target again, the second assert fails — which is the whole
    reason the milestone exists.
    """

    def test_adopted_try_has_intent_and_is_still_unresolved(self):
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        events = [retro, adopt]

        entry = self._retro_map(events)[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)
        self.assertEqual(entry["intent_by"], adopt["id"])

        resolutions = resolution.compute_resolutions(events)
        self.assertNotIn(TRY_ID, resolution.collect_all_resolved_ids(resolutions))

    def test_deferred_try_reports_deferred_with_a_defer_count(self):
        retro = make_retrospective_with_try(TRY_ID)
        defer = defer_try_event(self.smm_dir, TRY_ID)
        entry = self._retro_map([retro, defer])[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_DEFERRED)
        self.assertEqual(entry["defer_count"], 1)

    def test_untouched_try_has_no_intent(self):
        self.assertEqual(self._retro_map([make_retrospective_with_try(TRY_ID)]), {})


class TestCitedIdIsNotAdopted(_IntentTestCase):
    """THE headline regression. A Try's refs bag holds the Try id PLUS the debt
    ids its prose cites. A map keyed on the whole bag would mark that debt
    adopted because a Try mentioned it — laundering the debt inside the very
    story built to stop laundering.

    Live pair this reproduces: adopt 067031890483 references debt 9ec0731f5597,
    which is open and must stay offered.
    """

    def _events_with_cited_debt(self) -> tuple[list[dict], dict]:
        retro = make_retrospective_with_try(TRY_ID)
        debt = make_event(EVENT_TYPE_DEBT, content="The debt the Try is about")
        adopt = adopt_try_event(self.smm_dir, TRY_ID, cites=[debt["id"]])
        return [retro, debt, adopt], debt

    def test_cited_debt_has_no_intent_in_the_triage_map(self):
        events, debt = self._events_with_cited_debt()
        self.assertNotIn(debt["id"], self._triage_map(events))

    def test_cited_debt_has_no_intent_in_the_retro_map(self):
        """The `∩ try_ids` scope is what kills the bag leak: the debt id is in
        the adopt event's references, but it is not a Try id."""
        events, debt = self._events_with_cited_debt()
        retro_map = self._retro_map(events)
        self.assertNotIn(debt["id"], retro_map)
        self.assertIn(TRY_ID, retro_map)

    def test_the_bag_really_does_carry_both_ids(self):
        """Guard the guard: if the writer ever stopped putting BOTH ids in
        `references`, the two tests above would pass vacuously."""
        events, debt = self._events_with_cited_debt()
        adopt = events[-1]
        self.assertEqual(sorted(adopt["references"]), sorted([TRY_ID, debt["id"]]))


class TestReferenceIsNotIntent(_IntentTestCase):
    """A bare `references` link means nothing on its own — 6:1 false positives
    live. The lane tag is what makes an intent link readable."""

    def test_stale_question_concern_does_not_adopt_the_question(self):
        """The auto-raised concern whose WHOLE PURPOSE is to say the question is
        being IGNORED references that question. Reading `references` as intent
        would file it as `adopted`."""
        question = make_event(EVENT_TYPE_QUESTION, content="A blocking question")
        stale = make_event(
            EVENT_TYPE_CONCERN,
            content=(
                f"Stale question: blocking question {question['id']} "
                "has not been answered"
            ),
            references=[question["id"]],
        )
        events = [question, stale]
        self.assertNotIn(question["id"], self._triage_map(events))
        self.assertNotIn(question["id"], self._retro_map(events))

    def test_a_drop_is_not_an_intent(self):
        """Drops are terminal — `metadata.resolves`, and resolution.py's job."""
        retro = make_retrospective_with_try(TRY_ID)
        drop = drop_try_event(self.smm_dir, TRY_ID)
        self.assertEqual(self._retro_map([retro, drop]), {})


class TestLaneScoping(_IntentTestCase):
    """Each lane reads only its own writer's events."""

    def test_retro_adopt_does_not_appear_in_the_triage_map(self):
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        self.assertEqual(self._triage_map([retro, adopt]), {})

    def test_triage_adopt_does_not_appear_in_the_retro_map(self):
        debt = make_event(EVENT_TYPE_DEBT, content="Adopted debt")
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])
        events = [debt, adopt]
        self.assertIn(debt["id"], self._triage_map(events))
        self.assertEqual(self._retro_map(events), {})


class TestTriageLane(_IntentTestCase):
    """AC3's read side: a triage-adopted debt carries intent and stays open."""

    def _triage(self, action: str) -> tuple[list[dict], dict, dict]:
        debt = make_event(EVENT_TYPE_DEBT, content="A debt under triage")
        self._write_events([debt])
        disposition_event = triage_event(self.smm_dir, action, debt["id"])
        return [debt, disposition_event], debt, disposition_event

    def test_triage_adopt_records_adopted_intent(self):
        events, debt, adopt = self._triage("triage-adopt")
        entry = self._triage_map(events)[debt["id"]]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)
        self.assertEqual(entry["intent_by"], adopt["id"])

    def test_triage_adopted_debt_stays_unresolved(self):
        events, debt, _ = self._triage("triage-adopt")
        resolutions = resolution.compute_resolutions(events)
        self.assertNotIn(debt["id"], resolution.collect_all_resolved_ids(resolutions))

    def test_triage_defer_records_deferred_intent(self):
        """A defer says something durable — the user saw it and chose not now.
        An unlinked defer is undetectable by construction."""
        events, debt, _ = self._triage("triage-defer")
        entry = self._triage_map(events)[debt["id"]]
        self.assertEqual(entry["intent"], DISPOSITION_DEFERRED)
        self.assertEqual(entry["defer_count"], 1)

    def test_triage_deferred_debt_stays_unresolved(self):
        """Linking is NOT closing: the deferred debt must remain offered."""
        events, debt, _ = self._triage("triage-defer")
        resolutions = resolution.compute_resolutions(events)
        self.assertNotIn(debt["id"], resolution.collect_all_resolved_ids(resolutions))

    def test_triage_drop_is_terminal_not_intent(self):
        events, debt, _ = self._triage("triage-drop")
        self.assertNotIn(debt["id"], self._triage_map(events))
        resolutions = resolution.compute_resolutions(events)
        self.assertIn(debt["id"], resolution.collect_all_resolved_ids(resolutions))


class TestPrecedence(_IntentTestCase):
    """AC4. Terminal beats intent; among intents the LAST one in FILE ORDER wins."""

    def test_adopted_then_dropped_reads_dropped(self):
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        drop = drop_try_event(self.smm_dir, TRY_ID)
        events = [retro, adopt, drop]
        # Terminal wins: no intent survives, and the Try reads as resolved.
        self.assertEqual(self._retro_map(events), {})
        resolutions = resolution.compute_resolutions(events)
        self.assertIn(TRY_ID, resolution.collect_all_resolved_ids(resolutions))

    def test_deferred_twice_then_adopted_reads_adopted(self):
        retro = make_retrospective_with_try(TRY_ID)
        events = [
            retro,
            defer_try_event(self.smm_dir, TRY_ID),
            defer_try_event(self.smm_dir, TRY_ID),
            adopt_try_event(self.smm_dir, TRY_ID),
        ]
        entry = self._retro_map(events)[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)
        self.assertEqual(entry["defer_count"], 2)

    def test_ordering_is_file_position_not_ts(self):
        """`ts` is stamped BEFORE the flock, so under concurrent writers ts order
        and causal order disagree. The log is append-only and flock-serialized,
        so FILE ORDER is causal order. Invert the timestamps: the later-in-file
        adopt must still win over the earlier-in-file defer.
        """
        retro = make_retrospective_with_try(TRY_ID)
        defer = defer_try_event(self.smm_dir, TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        defer["ts"] = "2026-07-12T10:00:02+00:00"
        adopt["ts"] = "2026-07-12T10:00:01+00:00"  # earlier ts, later in file

        entry = self._retro_map([retro, defer, adopt])[TRY_ID]
        self.assertEqual(entry["intent"], DISPOSITION_ADOPTED)


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
