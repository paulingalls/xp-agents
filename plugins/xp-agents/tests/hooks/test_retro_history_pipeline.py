#!/usr/bin/env python3
"""Tests for retro_history.py: gather + save pipeline + end-to-end Try resolution.

Covers TestRetroHistoryConstants, TestGatherRetroHistoryAnalysisNotes,
TestTryItemIdResolution, TestEndToEndTryDispositionPipeline,
TestSaveRetroStampsTryIds. Annotation-level tests live in
test_retro_history.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_history
from conftest import _HookTestCase, make_event, make_retrospective_with_try
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_STATUS,
)


class TestRetroHistoryConstants(unittest.TestCase):
    """MAX_RETRO_HISTORY should be 1 — only the most recent retro is needed."""

    def test_max_retro_history_is_1(self):
        self.assertEqual(retro_history.MAX_RETRO_HISTORY, 1)


class TestGatherRetroHistoryAnalysisNotes(_HookTestCase):
    """gather_retro_history should include analysis_notes in the slim."""

    def setUp(self):
        super().setUp()
        self.retro_dir = self.smm_dir / "retrospectives"
        self.retro_dir.mkdir()

    def _write_retro(self, filename: str, data: dict) -> None:
        (self.retro_dir / filename).write_text(json.dumps(data))

    def test_gather_includes_analysis_notes(self):
        self._write_retro(
            "2026-04-20T00-00-00.json",
            {
                "timestamp": "2026-04-20T00:00:00+00:00",
                "keep": [{"content": "Good"}],
                "fix": [],
                "try": [],
                "analysis_notes": "Third consecutive sprint with sizing inversion",
            },
        )
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["analysis_notes"],
            "Third consecutive sprint with sizing inversion",
        )

    def test_gather_omits_analysis_notes_when_absent(self):
        self._write_retro(
            "2026-04-20T00-00-00.json",
            {
                "timestamp": "2026-04-20T00:00:00+00:00",
                "keep": [],
                "fix": [],
                "try": [],
            },
        )
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result), 1)
        self.assertNotIn("analysis_notes", result[0])

    def test_only_one_retro_returned(self):
        for i in range(3):
            self._write_retro(
                f"2026-04-{20 + i:02d}T00-00-00.json",
                {
                    "timestamp": f"2026-04-{20 + i:02d}T00:00:00+00:00",
                    "keep": [],
                    "fix": [],
                    "try": [],
                },
            )
        result = retro_history.gather_retro_history(self.smm_dir)
        self.assertEqual(len(result), 1)

    def test_gather_preserves_try_id_for_annotation(self):
        """A retro file's Try item id must survive slimming so annotate_try_status
        can match it. Without the id, Try items with no event_refs and no hex
        token in their prose can never be matched at all (concern c5cb2ea74247).

        Driven through the real adopt writer: the id survives iff the Try comes
        back carrying the adoption's intent.
        """
        from conftest import adopt_try_event

        try_id = "abc111222333"
        self._write_retro(
            "2026-04-20T00-00-00.json",
            {
                "timestamp": "2026-04-20T00:00:00+00:00",
                "keep": [],
                "fix": [],
                "try": [
                    {
                        "id": try_id,
                        "content": "Improve process with no event refs",
                        "event_refs": [],
                    }
                ],
            },
        )
        gathered = retro_history.gather_retro_history(self.smm_dir)
        events = [
            make_retrospective_with_try(try_id, "Improve process with no event refs"),
            adopt_try_event(self.smm_dir, try_id),
        ]
        retro_history.annotate_try_status(gathered, {}, events)
        status = gathered[0]["try_status"][0]
        self.assertEqual(status["intent"], "adopted")
        self.assertFalse(status["resolved_this_session"])


class TestTryItemIdResolution(unittest.TestCase):
    """Try items with their own id field should be resolvable by that id."""

    def _make_resolutions_map(self, target_id, resolver_id):
        return {
            target_id: {
                "type": "other",
                "resolver_id": resolver_id,
                "resolver_type": "decision",
                "resolver_content": "Adopted",
            }
        }

    def test_try_item_resolved_by_own_id(self):
        """A Try item with an id field is resolved when that id
        appears in the resolutions_map — even without event_refs
        or hex tokens in content."""
        try_id = "aabb11223344"
        retros = [
            {
                "try": [
                    {
                        "id": try_id,
                        "content": "Improve process with no event refs",
                        "event_refs": [],
                    }
                ],
                "keep": [],
                "fix": [],
            }
        ]
        rmap = self._make_resolutions_map(try_id, "resolver999999")
        retro_history.annotate_try_status(retros, rmap, [])
        status = retros[0]["try_status"][0]
        self.assertTrue(status["resolved_this_session"])

    def test_try_item_without_id_still_unresolved(self):
        retros = [
            {
                "try": [{"content": "Process improvement no refs", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, {}, [])
        status = retros[0]["try_status"][0]
        self.assertFalse(status["resolved_this_session"])


class TestEndToEndTryDispositionPipeline(_HookTestCase):
    """Pin the full compute_resolutions → build_resolutions_map →
    annotate_try_status pipeline. A status event with metadata.resolves=
    [try_id] disposition=dropped must propagate to the latest retro's
    try_status with disposition="dropped", AND the try MUST remain in
    latest.try so the retro agent prompt rule "disposition='dropped' —
    do not re-propose" at xp-retrospective.md:208 is reachable.

    Cross-session memory is double-walled: digest.dropped_tries_recent
    surfaces drops from any session, and try_status[i].disposition
    surfaces the most-recent retro's drops in their original Try slot.
    """

    def test_drop_via_metadata_resolves_preserves_try_with_disposition(self):
        import resolution
        from retro_metrics import build_resolutions_map

        try_id = "ee11ff2233aa"
        retro_event = make_retrospective_with_try(try_id, "Try to be dropped")
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="User dropped the try",
            working_on=[],
            metadata={"resolves": [try_id], "disposition": "dropped"},
        )
        events = [retro_event, dropper]

        resolutions = resolution.compute_resolutions(events)
        rmap = build_resolutions_map(resolutions)

        retros = [
            {
                "try": [
                    {"id": try_id, "content": "Try to be dropped", "event_refs": []}
                ],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, rmap, events)

        # Dropped tries are PRESERVED with disposition="dropped" so the
        # agent prompt rule at xp-retrospective.md:208 is reachable.
        self.assertEqual(len(retros[0]["try"]), 1)
        self.assertEqual(retros[0]["try"][0]["id"], try_id)
        self.assertEqual(len(retros[0]["try_status"]), 1)
        self.assertTrue(retros[0]["try_status"][0]["resolved_this_session"])
        self.assertEqual(retros[0]["try_status"][0]["disposition"], "dropped")

    def test_adopt_via_the_real_writer_reports_intent_and_stays_unresolved(self):
        """AC1 end-to-end, through the same pipeline production runs.

        This test used to build a `decision` carrying metadata.resolves and
        assert the Try came back RESOLVED. No writer has produced that shape
        since adoption stopped closing its target — the test was green while
        production was broken, which is the exact failure this story is about.
        It now calls the real writer, and asserts BOTH halves: the Try reports
        intent=adopted, and compute_resolutions still reports it UNRESOLVED.
        """
        import resolution
        from conftest import adopt_try_event
        from retro_metrics import build_resolutions_map

        try_id = "aa22bb3344cc"
        retro_event = make_retrospective_with_try(try_id, "Try to adopt")
        adopter = adopt_try_event(self.smm_dir, try_id)
        events = [retro_event, adopter]

        resolutions = resolution.compute_resolutions(events)
        rmap = build_resolutions_map(resolutions)

        retros = [
            {
                "try": [{"id": try_id, "content": "Try to adopt", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, rmap, events)

        status = retros[0]["try_status"][0]
        self.assertEqual(len(retros[0]["try"]), 1)
        self.assertEqual(status["intent"], "adopted")
        self.assertEqual(status["intent_by"], adopter["id"])
        # Linking is not closing: adoption must NOT resolve the Try.
        self.assertFalse(status["resolved_this_session"])
        self.assertNotIn(try_id, resolution.collect_all_resolved_ids(resolutions))

    def test_cascade_does_not_close_unrelated_event_referencing_retro_try(self):
        """Concern ade2305a435a: synthetic retro_try entries are visible to
        the cascade pass. A real event whose top-level references list
        contains a try-id should NOT be cascade-closed off the synthetic
        target — synthetics never appear as resolved targets to cascade
        because compute_resolutions only iterates the events list (not
        by_id) for the cascade pass. Pin this so future refactors don't
        regress it.
        """
        import resolution

        try_id = "bb33cc4455dd"
        retro_event = make_retrospective_with_try(try_id, "Try referenced by a concern")

        # Real concern event references the try-id but the try is unresolved.
        concern_referencing_try = make_event(
            EVENT_TYPE_CONCERN,
            content="Concern that references a try-id (no resolver in events)",
            references=[try_id],
        )
        events = [retro_event, concern_referencing_try]

        resolutions = resolution.compute_resolutions(events)

        # The concern is NOT cascade-closed because nothing resolved the try.
        self.assertNotIn(
            concern_referencing_try["id"], resolutions["resolved_concern_ids"]
        )
        # The try itself is also unresolved (no resolver in events).
        self.assertNotIn(try_id, resolutions["resolved_other_ids"])

    def test_cascade_closes_event_referencing_resolved_retro_try(self):
        """When the try IS resolved (by adopt/drop), an event whose
        references list contains the try-id IS cascade-closed. This is
        the intended STRONG→WEAK cascade behavior — same semantics as
        any other resolved target, applied uniformly.
        """
        import resolution

        try_id = "cc44dd5566ee"
        retro_event = make_retrospective_with_try(try_id, "Try to drop")
        dropper = make_event(
            EVENT_TYPE_STATUS,
            content="Drop the try",
            working_on=[],
            metadata={"resolves": [try_id], "disposition": "dropped"},
        )
        # An unrelated debt that references the try; cascade should close it.
        debt_referencing_try = make_event(
            EVENT_TYPE_DEBT,
            content="Debt that depends on the try outcome",
            files=["scripts/x.py"],
            references=[try_id],
        )
        events = [retro_event, dropper, debt_referencing_try]

        resolutions = resolution.compute_resolutions(events)

        # The debt cascade-closes off the dropper (the resolver of the try).
        self.assertIn(debt_referencing_try["id"], resolutions["resolved_debt_ids"])


class TestSaveRetroStampsTryIds(unittest.TestCase):
    """save_retrospective.run() stamps each Try item with a unique id."""

    def test_try_items_get_ids(self):
        import tempfile

        import save_retrospective

        kft = {
            "keep": [{"content": "Keep doing X"}],
            "fix": [{"content": "Fix Y"}],
            "try": [{"content": "Try A"}, {"content": "Try B"}],
        }
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            (smm_dir / "events.jsonl").write_text("")
            (smm_dir / "retrospectives").mkdir()
            result = save_retrospective.run(kft, smm_dir=smm_dir)
            assert result is not None

            retro = json.loads(Path(result["retro_file"]).read_text())
            for item in retro["try"]:
                self.assertIn("id", item, f"Try item missing id: {item}")
                self.assertEqual(len(item["id"]), 12)

    def test_existing_ids_preserved(self):
        import tempfile

        import save_retrospective

        kft = {
            "keep": [],
            "fix": [],
            "try": [{"content": "Try A", "id": "existing00001"}],
        }
        with tempfile.TemporaryDirectory() as td:
            smm_dir = Path(td)
            (smm_dir / "events.jsonl").write_text("")
            (smm_dir / "retrospectives").mkdir()
            result = save_retrospective.run(kft, smm_dir=smm_dir)
            assert result is not None

            retro = json.loads(Path(result["retro_file"]).read_text())
            self.assertEqual(retro["try"][0]["id"], "existing00001")


if __name__ == "__main__":
    unittest.main()
