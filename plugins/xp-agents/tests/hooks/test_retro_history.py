#!/usr/bin/env python3
"""Tests for retro_history.py: Try-item annotation, disposition tracking,
resolutions-map propagation, and preload Try-item filtering.

Gather/save/end-to-end pipeline tests live in test_retro_history_pipeline.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_history
from conftest import _HookTestCase, make_event
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS


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
        from retro_metrics import build_resolutions_map

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
        from retro_metrics import build_resolutions_map

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


if __name__ == "__main__":
    unittest.main()
