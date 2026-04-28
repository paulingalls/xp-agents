#!/usr/bin/env python3
"""Tests for retro_history.py: Try-item annotation with disposition tracking."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_history
from conftest import _HookTestCase, make_event, make_retrospective_with_try


class TestAnnotateTryDisposition(_HookTestCase):
    """annotate_try_status should report disposition from resolver metadata."""

    def _make_resolutions_map(self, target_id, resolver_id, content, disposition=None):
        entry = {
            "type": "other",
            "resolver_id": resolver_id,
            "resolver_type": "decision",
            "resolver_content": content,
        }
        if disposition is not None:
            entry["disposition"] = disposition
        return {target_id: entry}

    def test_adopted_try_gets_disposition_adopted(self):
        target_id = "aabbccdd1111"
        resolver_id = "eeffaabb5555"
        resolutions_map = self._make_resolutions_map(
            target_id, resolver_id, "Adopted retro Try: kickoff exemption"
        )
        retros = [
            {
                "try": [{"content": f"implement {target_id}", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        status = retros[0]["try_status"][0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status.get("disposition"), "adopted")

    def test_dropped_try_gets_disposition_dropped(self):
        """Dropped Try is stripped — verify via empty lists."""
        target_id = "aabbccdd1111"
        resolver_id = "eeffaabb5555"
        resolutions_map = self._make_resolutions_map(
            target_id, resolver_id, "Dropped retro Try: not worth it", "dropped"
        )
        retros = [
            {
                "try": [{"content": f"try {target_id}", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        self.assertEqual(len(retros[0]["try"]), 0)
        self.assertEqual(len(retros[0]["try_status"]), 0)

    def test_deferred_try_gets_disposition_deferred(self):
        target_id = "aabbccdd1111"
        resolver_id = "eeffaabb5555"
        resolutions_map = self._make_resolutions_map(
            target_id, resolver_id, "Deferred retro Try: next session", "deferred"
        )
        retros = [
            {
                "try": [{"content": f"try {target_id}", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        status = retros[0]["try_status"][0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["disposition"], "deferred")

    def test_unresolved_try_has_no_disposition(self):
        retros = [
            {
                "try": [{"content": "unmatched try item", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, {})
        status = retros[0]["try_status"][0]
        self.assertFalse(status["resolved_this_session"])
        self.assertNotIn("disposition", status)

    def test_adopted_try_remains_in_try_list(self):
        """Adopted Tries stay visible for the LLM to check if work was delivered."""
        target_id = "aabbccdd1111"
        resolver_id = "eeffaabb5555"
        resolutions_map = self._make_resolutions_map(target_id, resolver_id, "Adopted")
        retros = [
            {
                "try": [{"content": f"try {target_id}", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        self.assertEqual(len(retros[0]["try"]), 1)
        self.assertEqual(len(retros[0]["try_status"]), 1)

    def test_mixed_dispositions_only_drops_stripped(self):
        """Only dropped Tries are stripped; adopted and unresolved remain."""
        drop_id = "dd0011111111"
        adopt_id = "aa0022222222"
        resolutions_map = {
            drop_id: {
                "type": "other",
                "resolver_id": "r1",
                "resolver_type": "status",
                "resolver_content": "Dropped",
                "disposition": "dropped",
            },
            adopt_id: {
                "type": "other",
                "resolver_id": "r2",
                "resolver_type": "decision",
                "resolver_content": "Adopted",
            },
        }
        retros = [
            {
                "try": [
                    {"content": f"try {adopt_id}", "event_refs": []},
                    {"content": f"try {drop_id}", "event_refs": []},
                    {"content": "unresolved try", "event_refs": []},
                ],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        self.assertEqual(len(retros[0]["try"]), 2)
        contents = [t["content"] for t in retros[0]["try"]]
        self.assertIn(f"try {adopt_id}", contents)
        self.assertIn("unresolved try", contents)
        self.assertNotIn(f"try {drop_id}", contents)
        self.assertEqual(len(retros[0]["try_status"]), 2)

    def test_decision_resolver_without_disposition_defaults_to_adopted(self):
        """A decision event without explicit disposition metadata is an adoption."""
        target_id = "aabbccdd1111"
        resolver_id = "eeffaabb5555"
        resolutions_map = self._make_resolutions_map(
            target_id, resolver_id, "Adopted retro Try: something"
        )
        retros = [
            {
                "try": [{"content": f"try {target_id}", "event_refs": []}],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, resolutions_map)
        status = retros[0]["try_status"][0]
        self.assertEqual(status["disposition"], "adopted")


class TestBuildResolutionsMapDisposition(_HookTestCase):
    """build_resolutions_map should propagate disposition from resolver metadata."""

    def test_disposition_propagated_from_resolver_metadata(self):
        from retro_metrics import build_resolutions_map

        target_id = "aabbccdd1111"
        resolver = make_event(
            "status",
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
        from retro_metrics import build_resolutions_map

        target_id = "aabbccdd1111"
        resolver = make_event(
            "status",
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
        from retro_metrics import build_resolutions_map

        target_id = "aabbccdd1111"
        resolver = make_event(
            "decision",
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


class TestGetTryItemsFiltering(unittest.TestCase):
    """get_try_items preload should skip resolved Try items.

    Tests the inline Python logic from _preload_base.sh get_try_items()
    directly, since sourcing the bash file requires a git repo.
    """

    @staticmethod
    def _filter_try_items(retro_data: dict) -> list[str]:
        """Replicate get_try_items() Python logic for testability."""
        items = retro_data.get("try", [])
        statuses = retro_data.get("try_status", [])
        lines: list[str] = []
        for i, item in enumerate(items):
            if i < len(statuses) and statuses[i].get("resolved_this_session"):
                continue
            c = item.get("content", item) if isinstance(item, dict) else item
            refs = item.get("event_refs", []) if isinstance(item, dict) else []
            if refs:
                lines.append(f"- {c} [refs: {', '.join(refs)}]")
            else:
                lines.append(f"- {c}")
        return lines

    def test_unresolved_items_shown(self):
        """Try items without try_status are shown."""
        data = {"try": [{"content": "Do X"}, {"content": "Do Y"}]}
        lines = self._filter_try_items(data)
        self.assertEqual(len(lines), 2)
        self.assertIn("Do X", lines[0])
        self.assertIn("Do Y", lines[1])

    def test_resolved_items_filtered(self):
        """Try items with resolved_this_session=True are filtered out."""
        data = {
            "try": [{"content": "Already adopted"}, {"content": "Still open"}],
            "try_status": [
                {"resolved_this_session": True, "disposition": "adopted"},
                {"resolved_this_session": False},
            ],
        }
        lines = self._filter_try_items(data)
        self.assertEqual(len(lines), 1)
        self.assertIn("Still open", lines[0])

    def test_all_resolved_returns_empty(self):
        """When all Try items are resolved, output is empty."""
        data = {
            "try": [{"content": "Done"}],
            "try_status": [{"resolved_this_session": True}],
        }
        lines = self._filter_try_items(data)
        self.assertEqual(len(lines), 0)

    def test_refs_preserved(self):
        """Event refs are included in output for unresolved items."""
        data = {
            "try": [{"content": "Fix X", "event_refs": ["abc123def456"]}],
        }
        lines = self._filter_try_items(data)
        self.assertIn("[refs: abc123def456]", lines[0])


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
        retro_history.annotate_try_status(retros, rmap)
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
        retro_history.annotate_try_status(retros, {})
        status = retros[0]["try_status"][0]
        self.assertFalse(status["resolved_this_session"])


class TestEndToEndTryDispositionPipeline(unittest.TestCase):
    """Pin the full compute_resolutions → build_resolutions_map →
    annotate_try_status pipeline. After A1 (resolution.py indexes nested
    try ids), a status event with metadata.resolves=[try_id]
    disposition=dropped must propagate to the latest retro's try_status
    AND strip the try from latest.try.

    Pre-A1, this only worked when the try happened to also share an
    event_ref with a top-level event. This test pins the direct path.
    """

    def test_drop_via_metadata_resolves_strips_try_end_to_end(self):
        import resolution
        from retro_metrics import build_resolutions_map

        try_id = "ee11ff2233aa"
        retro_event = make_retrospective_with_try(try_id, "Try to be dropped")
        dropper = make_event(
            "status",
            content="User dropped the try",
            working_on=[],
            metadata={"resolves": [try_id], "disposition": "dropped"},
        )
        events = [retro_event, dropper]

        resolutions = resolution.compute_resolutions(events)
        rmap = build_resolutions_map(resolutions)

        # Simulate the previous_retros list shape annotate_try_status expects.
        retros = [
            {
                "try": [
                    {"id": try_id, "content": "Try to be dropped", "event_refs": []}
                ],
                "keep": [],
                "fix": [],
            }
        ]
        retro_history.annotate_try_status(retros, rmap)

        # Dropped tries are stripped from latest.try
        self.assertEqual(retros[0]["try"], [])
        self.assertEqual(retros[0]["try_status"], [])

    def test_adopt_via_metadata_resolves_marks_resolved_and_keeps_try(self):
        """When a decision adopts a try via metadata.resolves, the try is
        kept (not stripped — only dropped tries are stripped), marked
        resolved_this_session, and gets disposition='adopted' from the
        resolver_type fallback in annotate_try_status.
        """
        import resolution
        from retro_metrics import build_resolutions_map

        try_id = "aa22bb3344cc"
        retro_event = make_retrospective_with_try(try_id, "Try to adopt")
        adopter = make_event(
            "decision",
            content="Adopt the try",
            topic="retro-try-adopt",
            metadata={"resolves": [try_id]},
        )
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
        retro_history.annotate_try_status(retros, rmap)

        self.assertEqual(len(retros[0]["try"]), 1)  # adopted, not stripped
        self.assertTrue(retros[0]["try_status"][0]["resolved_this_session"])
        self.assertEqual(retros[0]["try_status"][0]["disposition"], "adopted")

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
            "concern",
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
            "status",
            content="Drop the try",
            working_on=[],
            metadata={"resolves": [try_id], "disposition": "dropped"},
        )
        # An unrelated debt that references the try; cascade should close it.
        debt_referencing_try = make_event(
            "debt",
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
            self.assertIsNotNone(result)

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
            self.assertIsNotNone(result)

            retro = json.loads(Path(result["retro_file"]).read_text())
            self.assertEqual(retro["try"][0]["id"], "existing00001")


if __name__ == "__main__":
    unittest.main()
