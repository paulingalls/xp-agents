#!/usr/bin/env python3
"""Tests for triage_preload: scan events for unresolved items."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import triage_preload
from conftest import _SMMTestCase, make_event
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)


class TestFormatTriageSection(unittest.TestCase):
    """format_triage_section produces markdown triage output."""

    def test_formats_with_aging(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fix auth",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_ends = [
            "2026-02-01T00:00:00+00:00",
            "2026-03-01T00:00:00+00:00",
        ]
        result = triage_preload.format_triage_section(
            "Open Debts", [item], session_ends
        )
        self.assertIn("### Open Debts:", result)
        self.assertIn(f"[id: {item['id']}]", result)
        self.assertIn("Fix auth", result)
        self.assertIn("2 sessions old", result)

    def test_singular_session(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fix it",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_ends = ["2026-02-01T00:00:00+00:00"]
        result = triage_preload.format_triage_section(
            "Open Debts", [item], session_ends
        )
        self.assertIn("1 session old", result)

    def test_empty_items_returns_empty(self):
        result = triage_preload.format_triage_section("Open Debts", [], [])
        self.assertEqual(result, "")

    def test_zero_age(self):
        item = make_event(
            EVENT_TYPE_DEBT,
            content="Fresh",
            ts="2026-04-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Debts", [item], [])
        self.assertIn("0 sessions old", result)


class TestRun(_SMMTestCase):
    """run() produces complete triage output from events."""

    def test_outputs_all_three_sections(self):
        d = make_event(EVENT_TYPE_DEBT, content="A debt item")
        c = make_event(EVENT_TYPE_CONCERN, content="A concern item")
        q = make_event(EVENT_TYPE_QUESTION, content="A question item")
        self._write_events([d, c, q])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertIn("### Open Concerns:", output)
        self.assertIn("### Open Questions:", output)

    def test_excludes_resolved_events(self):
        d = make_event(EVENT_TYPE_DEBT, content="Resolved debt")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            metadata={"resolves": [d["id"]]},
        )
        self._write_events([d, resolver])

        output = triage_preload.run(self.smm_dir)
        self.assertNotIn("Resolved debt", output)

    def test_empty_events_returns_empty(self):
        output = triage_preload.run(self.smm_dir)
        self.assertEqual(output, "")

    def test_omits_empty_sections(self):
        d = make_event(EVENT_TYPE_DEBT, content="Only debt")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertNotIn("### Open Concerns:", output)
        self.assertNotIn("### Open Questions:", output)

    def test_includes_event_ids(self):
        d = make_event(EVENT_TYPE_DEBT, content="Track me")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn(f"[id: {d['id']}]", output)


class TestFormatWithOverlap(unittest.TestCase):
    """format_triage_section annotates concerns with commit overlap."""

    def test_annotated_concern_shows_maybe_addressed(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="Fix token leak in auth",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        overlap = {concern["id"]: [commit]}
        result = triage_preload.format_triage_section(
            "Open Concerns", [concern], [], commit_overlap=overlap
        )
        self.assertIn("MAYBE ADDRESSED", result)
        self.assertIn("Fix token leak", result)

    def test_no_annotation_without_overlap(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth bug",
            ts="2026-01-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Concerns", [concern], [])
        self.assertNotIn("MAYBE ADDRESSED", result)


class TestRunWithOverlap(_SMMTestCase):
    """run() annotates concerns with commit overlap in output."""

    def test_concern_with_overlap_annotated(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth validation bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="Fix auth validation",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([concern, commit])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("MAYBE ADDRESSED", output)
        self.assertIn("Fix auth validation", output)

    def test_concern_cited_by_commit_id_annotated_without_file_overlap(self):
        """A commit that cites the concern's id in its body (no file
        overlap) still surfaces under MAYBE ADDRESSED — exercises the
        find_addressing_commits id tier wiring."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Auth validation bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content=f"Fix landed in helper, closes {concern['id']}",
            files=["scripts/helper.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([concern, commit])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("MAYBE ADDRESSED", output)
        self.assertIn(concern["id"], output)


if __name__ == "__main__":
    unittest.main()
