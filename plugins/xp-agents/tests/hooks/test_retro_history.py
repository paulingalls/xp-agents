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

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_history
from _retro_annotate_fixtures import _AnnotateTestCase
from conftest import (
    _HookTestCase,
    adopt_try_event,
    defer_try_event,
    make_event,
    make_retrospective_with_try,
)
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_STATUS,
)
from retro_metrics import build_resolutions_map


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


class TestTryStatusProseContract(unittest.TestCase):
    """The retro agent's PROMPT is the only gate on re-proposing an adopted Try.

    No code filters adopted Tries out of the agent's input — the prose is what
    stops the re-proposal, which makes `agents/xp-retrospective.md` production
    code with a contract to honour. A green suite otherwise proves NOTHING about
    this seam, and it has already drifted once: the closure channel can report
    `disposition="deferred"` (a legacy defer that closed its target), and the
    bullet telling the agent what to do with that state was deleted while the
    code kept emitting it. The agent's fallback for an uncovered state is to read
    `resolved_this_session: true` as "landed" — a carried Try reported as
    delivered, the exact amnesia this milestone exists to end.

    What this pins, honestly:
      * every field key `_try_status` can emit is NAMED in the prose;
      * every value each channel can carry is SPELLED WITH ITS CHANNEL
        (`disposition: "deferred"`, not merely the word "deferred" somewhere) —
        the pairing is the rule the agent acts on, and a bare mention elsewhere
        is what let the deleted bullet slip through review.

    What it does NOT pin: that the prose's ADVICE for a state is correct. That
    stays human judgement. This is a floor, not a ceiling.

    Keys are DERIVED by driving `_try_status` across every state it can reach,
    never hardcoded — a hardcoded list is a second copy that drifts in its own
    right.
    """

    def _emitted_keys(self) -> set[str]:
        """Union of the keys `_try_status` emits across every reachable state."""
        item = {"id": "a" * 12, "content": "carry the thing", "event_refs": []}
        closure = {"resolver_id": "b" * 12, "resolver_type": "status"}
        states = [
            # CLOSURE channel: landed (no disposition), and each disposition
            # build_resolutions_map can pass through from a resolver event.
            ({item["id"]: closure}, {}),
            ({item["id"]: {**closure, "disposition": "dropped"}}, {}),
            ({item["id"]: {**closure, "disposition": "deferred"}}, {}),
            ({item["id"]: {**closure, "disposition": "adopted"}}, {}),
            # Legacy closing adoption: a `decision` resolver with no disposition.
            ({item["id"]: {**closure, "resolver_type": EVENT_TYPE_DECISION}}, {}),
            # INTENT channel.
            (
                {},
                {
                    item["id"]: {
                        "intent": "adopted",
                        "intent_by": "c" * 12,
                        "intent_ts": "2026-01-01T00:00:00Z",
                        "defer_count": 0,
                    }
                },
            ),
            (
                {},
                {
                    item["id"]: {
                        "intent": "deferred",
                        "intent_by": "c" * 12,
                        "intent_ts": "2026-01-01T00:00:00Z",
                        "defer_count": 3,
                    }
                },
            ),
            # Neither channel.
            ({}, {}),
        ]
        keys: set[str] = set()
        for resolutions_map, intent_map in states:
            keys |= set(retro_history._try_status(item, resolutions_map, intent_map))
        return keys

    def test_agent_prose_names_every_field_try_status_emits(self):
        prose = (
            Path(__file__).parent.parent.parent / "agents" / "xp-retrospective.md"
        ).read_text(encoding="utf-8")
        missing = sorted(k for k in self._emitted_keys() if k not in prose)
        self.assertFalse(
            missing,
            "agents/xp-retrospective.md does not name these try_status fields, "
            f"so the agent cannot act on them: {missing}. The prose is the only "
            "gate on re-proposing an adopted Try — update it.",
        )

    def test_agent_prose_pairs_every_value_with_its_channel(self):
        """Each value must be spelled WITH the channel that carries it.

        A bare `"deferred"` somewhere in the prose is not a rule — the agent acts
        on `<channel>: "<value>"`. Asserting the pairing is what makes this catch
        the deleted `disposition: "deferred"` bullet; asserting the bare word
        does not, because the intent bullet mentions it too.
        """
        prose = (
            Path(__file__).parent.parent.parent / "agents" / "xp-retrospective.md"
        ).read_text(encoding="utf-8")
        # CLOSURE carries every disposition build_resolutions_map passes through
        # from a resolver event; INTENT carries only the non-terminal two.
        pairings = [
            ("disposition", "adopted"),
            ("disposition", "deferred"),
            ("disposition", "dropped"),
            ("intent", "adopted"),
            ("intent", "deferred"),
        ]
        for channel, value in pairings:
            with self.subTest(channel=channel, value=value):
                self.assertIn(
                    f'{channel}: "{value}"',
                    prose,
                    f"try_status can report {channel}={value!r}, but the agent "
                    f"prose never states that pairing — so the agent has no rule "
                    f"for that state and will fall back to reading it as landed.",
                )


if __name__ == "__main__":
    unittest.main()
