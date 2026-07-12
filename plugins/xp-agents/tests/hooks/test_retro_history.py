#!/usr/bin/env python3
"""Tests for retro_history.py: Try-item annotation, disposition tracking,
resolutions-map propagation, and preload Try-item filtering.

Gather/save/end-to-end pipeline tests live in test_retro_history_pipeline.py.

Two channels, and keeping them apart is the point of this suite:

  * `resolved_this_session` + `disposition` — CLOSURE. The Try is finished with:
    dropped, or landed by a commit carrying a `Resolves-Event:` trailer.
  * `intent` (+ `intent_by` / `intent_ts` / `defer_count`) — INTENT. The Try was
    adopted or carried, and is still OPEN.

Overloading the first with the second is a new amnesia symmetric to the one this
story fixes: it would both hide the Try from work-selection AND declare it
implemented. `TestAdoptedTryIsNotResolved` pins that they stay separate.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import resolution
import retro_history
from conftest import (
    _HookTestCase,
    adopt_try_event,
    defer_try_event,
    make_event,
    make_retrospective_with_try,
)
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)
from retro_metrics import build_resolutions_map

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

# Reports `_candidate_ids(item)` from a FRESH interpreter, so the caller can
# choose its PYTHONHASHSEED. A set's iteration order is fixed for the life of a
# process, so this is the only way a test can see a set-ordering regression at
# all — see TestAnnotationIsDeterministic.
_CANDIDATE_ORDER_PROBE = (
    "import json,sys;sys.path.insert(0,sys.argv[1]);import retro_history;"
    "print(json.dumps(retro_history._candidate_ids(json.loads(sys.argv[2]))))"
)


def _candidate_ids_under_hash_seed(item: dict, seed: str) -> list[str]:
    """`_candidate_ids(item)` as computed by an interpreter run at `seed`."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _CANDIDATE_ORDER_PROBE,
            str(_SCRIPTS_DIR),
            json.dumps(item),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
        check=True,
    )
    return json.loads(result.stdout)


class _AnnotateTestCase(_HookTestCase):
    """Drives annotate_try_status the way retrospective.py drives it: the
    resolutions map and the intent map both derive from the same event list, so
    a test cannot hand the annotator a combination production never produces.
    """

    def _annotate(self, try_items: list[dict], events: list[dict]) -> list[dict]:
        retros = [{"try": try_items, "keep": [], "fix": []}]
        resolutions_map = build_resolutions_map(resolution.compute_resolutions(events))
        retro_history.annotate_try_status(retros, resolutions_map, events)
        return retros[0]["try_status"]

    def _try(self, try_id: str, content: str = "Carry this Try") -> dict:
        return {"id": try_id, "content": content, "event_refs": []}


class TestAdoptedTryIsNotResolved(_AnnotateTestCase):
    """AC1's reader half. An adopted Try reports intent=adopted and stays
    UNRESOLVED — adopted is not done."""

    TRY_ID = "aa11bb22cc33"

    def test_adopted_try_reports_intent_not_resolution(self):
        retro = make_retrospective_with_try(self.TRY_ID)
        adopt = adopt_try_event(self.smm_dir, self.TRY_ID)

        status = self._annotate([self._try(self.TRY_ID)], [retro, adopt])[0]

        self.assertEqual(status["intent"], "adopted")
        self.assertEqual(status["intent_by"], adopt["id"])
        self.assertFalse(status["resolved_this_session"])
        self.assertNotIn("disposition", status)

    def test_deferred_try_carries_its_defer_count(self):
        retro = make_retrospective_with_try(self.TRY_ID)
        events = [
            retro,
            defer_try_event(self.smm_dir, self.TRY_ID),
            defer_try_event(self.smm_dir, self.TRY_ID),
        ]
        status = self._annotate([self._try(self.TRY_ID)], events)[0]
        self.assertEqual(status["intent"], "deferred")
        self.assertEqual(status["defer_count"], 2)
        self.assertFalse(status["resolved_this_session"])

    def test_untouched_try_has_neither_channel(self):
        retro = make_retrospective_with_try(self.TRY_ID)
        status = self._annotate([self._try(self.TRY_ID)], [retro])[0]
        self.assertFalse(status["resolved_this_session"])
        self.assertNotIn("intent", status)
        self.assertNotIn("disposition", status)


class TestClosedTryReportsResolution(_AnnotateTestCase):
    """The closure channel still works, and terminal beats intent."""

    TRY_ID = "bb22cc33dd44"

    def test_dropped_try_reports_dropped(self):
        """Dropped Tries are NOT stripped — the agent prompt rule
        "disposition='dropped' — do not re-propose" needs to see them."""
        retro = make_retrospective_with_try(self.TRY_ID)
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop the Try",
            working_on=[],
            metadata={"resolves": [self.TRY_ID], "disposition": "dropped"},
        )
        status = self._annotate([self._try(self.TRY_ID)], [retro, dropper])[0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["disposition"], "dropped")
        self.assertEqual(status["resolver_id"], dropper["id"])

    def test_try_closed_by_a_commit_trailer_reports_resolved(self):
        """A commit whose `Resolves-Event:` trailer names the Try. This is the
        only leg that closes a Try by LANDING it — a drop (above) closes it too,
        but as a rejection. No disposition on the entry: a commit records no
        disposition, and the absence is what distinguishes landed from dropped.
        """
        retro = make_retrospective_with_try(self.TRY_ID)
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="Implement the adopted Try",
            metadata={"resolves": [self.TRY_ID]},
        )
        status = self._annotate([self._try(self.TRY_ID)], [retro, commit])[0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["resolver_id"], commit["id"])
        self.assertNotIn("intent", status)
        self.assertNotIn("disposition", status)

    def test_adopted_then_dropped_reads_dropped(self):
        """AC4. Terminal beats intent, whichever the reader meets first."""
        retro = make_retrospective_with_try(self.TRY_ID)
        adopt = adopt_try_event(self.smm_dir, self.TRY_ID)
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop it after all",
            working_on=[],
            metadata={"resolves": [self.TRY_ID], "disposition": "dropped"},
        )
        status = self._annotate([self._try(self.TRY_ID)], [retro, adopt, dropper])[0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["disposition"], "dropped")
        self.assertNotIn("intent", status)


class TestLegacyClosingAdoptionReadsAsAdopted(_AnnotateTestCase):
    """The one fixture in this suite that CANNOT come from the real writer, and
    the reason is the point: it is a shape only the log holds.

    Before adoption stopped closing its target, `/xp-work-selection adopt` wrote
    a `decision` carrying `metadata.resolves=[try_id]` and no disposition. No
    writer emits that today — but the reader does not read writers, it reads the
    log, and the log still holds these. One lives in this project's own SMM at
    `c6ff0efaa0bb` (topic `retro-try-verify-gating-claims`), and every shipped
    install that upgrades mid-cycle carries its own.

    Such a Try is CLOSED (`metadata.resolves` put it there), so `intent.py`
    excludes it from the intent map by design — the closure channel is the only
    one that can speak for it, and it must say `adopted`, not fall silent.
    Silence reads as "landed by a commit" (the sibling test above), which
    relabels a promise as delivery — the exact amnesia this story exists to end,
    pointing the other way.
    """

    TRY_ID = "dd44ee55ff66"

    def test_legacy_decision_closing_a_try_still_reports_adopted(self):
        retro = make_retrospective_with_try(self.TRY_ID)
        legacy_adopt = make_event(
            EVENT_TYPE_DECISION,
            content="Adopt the carried Try",
            topic="retro-try-legacy-shape",
            metadata={"resolves": [self.TRY_ID]},
        )
        status = self._annotate([self._try(self.TRY_ID)], [retro, legacy_adopt])[0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["resolver_id"], legacy_adopt["id"])
        self.assertEqual(status["disposition"], "adopted")


class TestAnnotationIsDeterministic(_AnnotateTestCase):
    """Story test 5. The old lookup built its candidate tokens as a SET and broke
    on the first hit, so which token matched depended on PYTHONHASHSEED. With a
    sparse map that rarely bit; a dense intent map makes the reported disposition
    a coin flip.

    Precedence is now explicit: own_id → event_refs (in order) → content tokens
    (in match order). The Try's OWN id is what the Try is; an id its prose cites
    is not.
    """

    TRY_ID = "cc33dd44ee55"

    def _events_where_own_id_and_cited_id_disagree(self):
        """The Try is DEFERRED. The debt its content cites is DROPPED. The two
        ids therefore carry different answers, and only one of them is the Try's.
        """
        retro = make_retrospective_with_try(self.TRY_ID)
        debt = make_event(EVENT_TYPE_DEBT, content="The cited debt")
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop the debt",
            working_on=[],
            metadata={"resolves": [debt["id"]], "disposition": "dropped"},
        )
        defer = defer_try_event(self.smm_dir, self.TRY_ID)
        return [retro, debt, dropper, defer], debt

    def test_own_id_wins_over_a_cited_id(self):
        events, debt = self._events_where_own_id_and_cited_id_disagree()
        item = {
            "id": self.TRY_ID,
            "content": f"Carry this Try, which is about {debt['id']}",
            "event_refs": [],
        }
        status = self._annotate([item], events)[0]
        # The Try is deferred. It is NOT the dropped debt.
        self.assertEqual(status["intent"], "deferred")
        self.assertFalse(status["resolved_this_session"])

    def test_candidate_order_holds_across_hash_seeds(self):
        """The regression this class exists to catch is a set's iteration order,
        which is a function of PYTHONHASHSEED — and the hash seed is fixed for
        the life of a process. Any in-process loop, however many iterations, gets
        the SAME set order every time and so can never see the bug: the previous
        version of this test ran the annotation 25x in one process and passed
        under a reverted set-based `_candidate_ids` on every seed tried.

        Varying the seed means varying the PROCESS. Each subprocess reports the
        candidate order for one Try whose own id, refs and content tokens all
        differ; a set-backed implementation disagrees with the declared
        precedence on all but a vanishing fraction of seeds, and disagrees
        BETWEEN seeds regardless.
        """
        item = {
            "id": "cc33dd44ee55",
            "event_refs": ["ref1ref1ref1", "ref2ref2ref2"],
            "content": "cites aaaaaaaaaaaa and bbbbbbbbbbbb",
        }
        expected = [
            "cc33dd44ee55",
            "ref1ref1ref1",
            "ref2ref2ref2",
            "aaaaaaaaaaaa",
            "bbbbbbbbbbbb",
        ]
        for seed in ("0", "1", "2", "3", "4"):
            with self.subTest(hash_seed=seed):
                self.assertEqual(_candidate_ids_under_hash_seed(item, seed), expected)

    def test_event_refs_beat_content_tokens(self):
        events, debt = self._events_where_own_id_and_cited_id_disagree()
        item = {
            "content": f"A Try with no id of its own, about {debt['id']}",
            "event_refs": [self.TRY_ID],
        }
        status = self._annotate([item], events)[0]
        self.assertEqual(status["intent"], "deferred")


class TestBuildResolutionsMapDisposition(_HookTestCase):
    """build_resolutions_map should propagate disposition from resolver metadata."""

    def test_disposition_propagated_from_resolver_metadata(self):
        target_id = "aabbccdd1111"
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Dropped retro Try: not useful",
            metadata={
                "resolves": [target_id],
                "disposition": "dropped",
            },
        )
        resolutions = {
            "concern_resolutions": {target_id: resolver},
            "goal_resolutions": {},
            "debt_resolutions": {},
            "decision_resolutions": {},
            "assumption_resolutions": {},
            "question_answers": {},
        }
        result = build_resolutions_map(resolutions)
        entry = result[target_id]
        self.assertEqual(entry["disposition"], "dropped")

    def test_other_resolutions_included_in_map(self):
        """Resolutions of status/sprint events should appear in the map."""
        target_id = "aabbccdd1111"
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Dropped retro Try: already fixed",
            metadata={
                "resolves": [target_id],
                "disposition": "dropped",
            },
        )
        resolutions = {
            "concern_resolutions": {},
            "goal_resolutions": {},
            "debt_resolutions": {},
            "decision_resolutions": {},
            "assumption_resolutions": {},
            "question_answers": {},
            "other_resolutions": {target_id: resolver},
        }
        result = build_resolutions_map(resolutions)
        self.assertIn(target_id, result)
        self.assertEqual(result[target_id]["disposition"], "dropped")

    def test_no_disposition_when_resolver_has_none(self):
        target_id = "aabbccdd1111"
        resolver = make_event(
            EVENT_TYPE_DECISION,
            content="Adopted retro Try: something",
            metadata={"resolves": [target_id]},
        )
        resolutions = {
            "concern_resolutions": {},
            "goal_resolutions": {},
            "debt_resolutions": {},
            "decision_resolutions": {target_id: resolver},
            "assumption_resolutions": {},
            "question_answers": {},
        }
        result = build_resolutions_map(resolutions)
        entry = result[target_id]
        self.assertNotIn("disposition", entry)


if __name__ == "__main__":
    unittest.main()
