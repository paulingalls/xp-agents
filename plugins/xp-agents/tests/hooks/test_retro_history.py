#!/usr/bin/env python3
"""Tests for retro_history.py: Try-item annotation with disposition tracking."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_history
from conftest import _HookTestCase, make_event


class TestAnnotateTryDisposition(_HookTestCase):
    """annotate_try_status should report disposition from resolver metadata."""

    def _make_resolutions_map(self, target_id, resolver_id, content, disposition=None):
        entry = {
            "type": "decision",
            "resolver_id": resolver_id,
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
        status = retros[0]["try_status"][0]
        self.assertTrue(status["resolved_this_session"])
        self.assertEqual(status["disposition"], "dropped")

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
    """_build_resolutions_map should propagate disposition from resolver metadata."""

    def test_disposition_propagated_from_resolver_metadata(self):
        from retrospective import _build_resolutions_map

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
        result = _build_resolutions_map(resolutions)
        entry = result[target_id]
        self.assertEqual(entry["disposition"], "dropped")

    def test_other_resolutions_included_in_map(self):
        """Resolutions of status/sprint events should appear in the map."""
        from retrospective import _build_resolutions_map

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
        result = _build_resolutions_map(resolutions)
        self.assertIn(target_id, result)
        self.assertEqual(result[target_id]["disposition"], "dropped")

    def test_no_disposition_when_resolver_has_none(self):
        from retrospective import _build_resolutions_map

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
        result = _build_resolutions_map(resolutions)
        entry = result[target_id]
        self.assertNotIn("disposition", entry)


if __name__ == "__main__":
    unittest.main()
