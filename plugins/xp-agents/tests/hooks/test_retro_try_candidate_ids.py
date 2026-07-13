#!/usr/bin/env python3
"""Which id ANSWERS for a retro Try — and which ids only look like they do.

Split from test_retro_history.py (over the 500-line cap) along the seam the bug
drew. A Try item carries three kinds of id and only one of them IS the Try:

  * its own `id`               — the Try itself.
  * its `event_refs`           — the debt/concern ids its prose is ABOUT.
  * hex tokens in its content  — the same, spelled inline.

`_try_status` walks these and takes the first that has an answer, and the two
channels it asks are scoped very differently. The INTENT map is keyed by Try ids
only (`intent.build_retro_intent_map` intersects `references ∩ try_ids`), so it
was always immune. The CLOSURE map is keyed by EVERY resolved id in the log — so
the walk fell THROUGH the Try's own id, which usually has no answer, onto a debt
the Try merely CITES, and reported that debt's closure as the Try's. A Try nobody
had done read as `resolved_this_session: True` and dropped out of re-proposal
forever. `TestClosureChannelIsScopedToTheTry` pins it.

The LEGACY Try (no id of its own) is the case that makes this subtle, and its
fallback is NOT the same leak: such an item has no other handle at all —
`_preload_base.get_try_items` renders its `[refs: ...]` bag from `event_refs`
alone, so a `/xp-work-selection drop` closes it by resolving the CITED id. Cut
the fallback and you do not fix a false positive; you delete the only closure
signal the item has. `TestAnnotationIsDeterministic` pins the ORDER it walks them
in, which is what decides the answer once more than one id is in play.
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

import retro_history
from _retro_annotate_fixtures import _AnnotateTestCase
from conftest import defer_try_event, make_event, make_retrospective_with_try
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_DEBT, EVENT_TYPE_STATUS

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
        candidate order for one Try whose refs and content tokens all differ; a
        set-backed implementation disagrees with the declared precedence on all
        but a vanishing fraction of seeds, and disagrees BETWEEN seeds regardless.

        Driven through a LEGACY item (no own id), which is the only shape whose
        candidate list still has more than one element — an id-carrying Try is
        answered by its own id alone (test_an_id_carrying_try_is_answered_by_its
        _own_id_alone). Order still decides which id answers there, so the pin is
        still load-bearing.
        """
        item = {
            "event_refs": ["ref1ref1ref1", "ref2ref2ref2"],
            "content": "cites aaaaaaaaaaaa and bbbbbbbbbbbb",
        }
        expected = [
            "ref1ref1ref1",
            "ref2ref2ref2",
            "aaaaaaaaaaaa",
            "bbbbbbbbbbbb",
        ]
        for seed in ("0", "1", "2", "3", "4"):
            with self.subTest(hash_seed=seed):
                self.assertEqual(_candidate_ids_under_hash_seed(item, seed), expected)

    def test_an_id_carrying_try_is_answered_by_its_own_id_alone(self):
        """Precedence was not enough. Ordering own_id first only decides which id
        is consulted FIRST — the walk still FALLS THROUGH to the refs and prose
        tokens whenever the Try's own id has no answer, which is the common case.
        Those ids are the debts/concerns the Try is ABOUT; none of them is the
        Try. There is nothing a fallback can add for an item that carries its own
        id, and everything for it to get wrong."""
        item = {
            "id": "cc33dd44ee55",
            "event_refs": ["ref1ref1ref1"],
            "content": "cites aaaaaaaaaaaa",
        }
        self.assertEqual(retro_history._candidate_ids(item), ["cc33dd44ee55"])

    def test_a_legacy_try_still_falls_back_to_its_refs(self):
        """The legacy fallback is NOT the same leak and must NOT be closed.

        A Try with no id of its own has no other handle: `get_try_items` renders
        its `[refs: ...]` bag from `event_refs` alone, so a `/xp-work-selection
        drop` of it writes `metadata.resolves: [<cited id>]` — the cited id IS
        how such a Try is closed. Filtering the refs out would not fix a false
        positive; it would delete the item's only closure signal and re-propose a
        Try that was explicitly dropped.
        """
        item = {
            "event_refs": ["ref1ref1ref1", "deadbeefdead"],
            "content": "cites aaaaaaaaaaaa",
        }
        self.assertEqual(
            retro_history._candidate_ids(item),
            ["ref1ref1ref1", "deadbeefdead", "aaaaaaaaaaaa"],
        )

    def test_event_refs_beat_content_tokens(self):
        events, debt = self._events_where_own_id_and_cited_id_disagree()
        item = {
            "content": f"A Try with no id of its own, about {debt['id']}",
            "event_refs": [self.TRY_ID],
        }
        status = self._annotate([item], events)[0]
        self.assertEqual(status["intent"], "deferred")


class TestClosureChannelIsScopedToTheTry(_AnnotateTestCase):
    """An id-carrying Try's closure is its OWN, and precedence alone did not
    deliver that.

    `resolutions_map` is keyed by EVERY resolved id in the log, so the walk over
    a Try's candidate ids falls THROUGH — past the Try's own id, which usually
    has no answer — onto the debt/concern ids the Try's prose merely CITES. A
    commit that closed one of those cited debts was then reported as the TRY's
    closure: `resolved_this_session: True`. The Try reads as done, drops out of
    re-proposal, and nobody ever does it.

    Same "a refs bag is not all its targets" hazard `intent.py` was designed
    around (`references ∩ try_ids`). The INTENT channel got that treatment and
    was immune; the closure channel did not.

    Scoped to Tries that CARRY an id. A legacy Try has no other handle — its
    `event_refs` are the only thing that can close it (see
    `test_a_legacy_try_still_falls_back_to_its_refs`), so the fallback stays.
    """

    TRY_ID = "cc33dd44ee55"

    def test_a_resolved_cited_debt_is_not_the_trys_resolution(self):
        retro = make_retrospective_with_try(self.TRY_ID)
        debt = make_event(EVENT_TYPE_DEBT, content="The cited debt")
        # A plain commit closes the DEBT. Nothing anywhere closes the Try.
        closer = make_event(
            EVENT_TYPE_COMMIT,
            content="Fix the cited debt",
            metadata={"resolves": [debt["id"]]},
        )
        item = {
            "id": self.TRY_ID,
            "content": f"Carry this Try, which is about {debt['id']}",
            "event_refs": [debt["id"]],
        }
        status = self._annotate([item], [retro, debt, closer])[0]
        self.assertFalse(
            status["resolved_this_session"],
            "a commit closing a debt the Try CITES does not close the Try",
        )
        self.assertNotIn("resolver_id", status)

    def test_the_trys_own_closure_is_still_reported(self):
        """The control. Scoping the channel must not disarm it: a drop naming the
        TRY's own id still reads as closed, with its disposition."""
        retro = make_retrospective_with_try(self.TRY_ID)
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop the Try",
            working_on=[],
            metadata={"resolves": [self.TRY_ID], "disposition": "dropped"},
        )
        item = {"id": self.TRY_ID, "content": "Carry this Try", "event_refs": []}
        status = self._annotate([item], [retro, dropper])[0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["disposition"], "dropped")


if __name__ == "__main__":
    unittest.main()
