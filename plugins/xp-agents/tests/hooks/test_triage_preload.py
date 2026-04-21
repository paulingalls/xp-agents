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


class TestFindUnresolved(_SMMTestCase):
    """find_unresolved filters and sorts events."""

    def test_returns_unresolved_debts(self):
        d1 = make_event("debt", content="Fix auth")
        d2 = make_event("debt", content="Fix logging")
        result = triage_preload.find_unresolved([d1, d2], "debt", set())
        self.assertEqual(len(result), 2)

    def test_excludes_resolved_events(self):
        d1 = make_event("debt", content="Fix auth")
        d2 = make_event("debt", content="Fix logging")
        result = triage_preload.find_unresolved([d1, d2], "debt", {d1["id"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Fix logging")

    def test_filters_by_type(self):
        d = make_event("debt", content="A debt")
        c = make_event("concern", content="A concern")
        result = triage_preload.find_unresolved([d, c], "debt", set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "A debt")

    def test_returns_newest_first(self):
        d1 = make_event("debt", content="Older", ts="2026-01-01T00:00:00+00:00")
        d2 = make_event("debt", content="Newer", ts="2026-04-01T00:00:00+00:00")
        result = triage_preload.find_unresolved([d1, d2], "debt", set())
        self.assertEqual(result[0]["content"], "Newer")
        self.assertEqual(result[1]["content"], "Older")

    def test_empty_when_no_matching_type(self):
        c = make_event("concern", content="A concern")
        result = triage_preload.find_unresolved([c], "debt", set())
        self.assertEqual(result, [])


class TestFormatTriageSection(unittest.TestCase):
    """format_triage_section produces markdown triage output."""

    def test_formats_with_aging(self):
        item = make_event(
            "debt",
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
            "debt",
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
            "debt",
            content="Fresh",
            ts="2026-04-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Debts", [item], [])
        self.assertIn("0 sessions old", result)


class TestRun(_SMMTestCase):
    """run() produces complete triage output from events."""

    def test_outputs_all_three_sections(self):
        d = make_event("debt", content="A debt item")
        c = make_event("concern", content="A concern item")
        q = make_event("question", content="A question item")
        self._write_events([d, c, q])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertIn("### Open Concerns:", output)
        self.assertIn("### Open Questions:", output)

    def test_excludes_resolved_events(self):
        d = make_event("debt", content="Resolved debt")
        resolver = make_event(
            "status",
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
        d = make_event("debt", content="Only debt")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn("### Open Debts:", output)
        self.assertNotIn("### Open Concerns:", output)
        self.assertNotIn("### Open Questions:", output)

    def test_includes_event_ids(self):
        d = make_event("debt", content="Track me")
        self._write_events([d])

        output = triage_preload.run(self.smm_dir)
        self.assertIn(f"[id: {d['id']}]", output)


class TestFindOverlappingCommits(unittest.TestCase):
    """find_overlapping_commits detects file overlap between concerns and commits."""

    def test_finds_overlap(self):
        concern = make_event(
            "concern",
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            "commit",
            content="Fix token leak",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        result = triage_preload.find_overlapping_commits(concern, [concern, commit])
        self.assertEqual(len(result), 1)
        self.assertIn("Fix token leak", result[0]["content"])

    def test_no_overlap_different_files(self):
        concern = make_event(
            "concern",
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            "commit",
            content="Fix db",
            files=["scripts/db.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        result = triage_preload.find_overlapping_commits(concern, [concern, commit])
        self.assertEqual(result, [])

    def test_no_overlap_without_files(self):
        concern = make_event(
            "concern",
            content="Vague concern",
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            "commit",
            content="Some change",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        result = triage_preload.find_overlapping_commits(concern, [concern, commit])
        self.assertEqual(result, [])

    def test_only_post_concern_commits(self):
        commit = make_event(
            "commit",
            content="Earlier fix",
            files=["scripts/auth.py"],
            ts="2025-12-01T00:00:00+00:00",
        )
        concern = make_event(
            "concern",
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        result = triage_preload.find_overlapping_commits(concern, [commit, concern])
        self.assertEqual(result, [])


class TestFormatWithOverlap(unittest.TestCase):
    """format_triage_section annotates concerns with commit overlap."""

    def test_annotated_concern_shows_likely_addressed(self):
        concern = make_event(
            "concern",
            content="Auth bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            "commit",
            content="Fix token leak in auth",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        overlap = {concern["id"]: [commit]}
        result = triage_preload.format_triage_section(
            "Open Concerns", [concern], [], commit_overlap=overlap
        )
        self.assertIn("LIKELY ADDRESSED", result)
        self.assertIn("Fix token leak", result)

    def test_no_annotation_without_overlap(self):
        concern = make_event(
            "concern",
            content="Auth bug",
            ts="2026-01-01T00:00:00+00:00",
        )
        result = triage_preload.format_triage_section("Open Concerns", [concern], [])
        self.assertNotIn("LIKELY ADDRESSED", result)


class TestRunWithOverlap(_SMMTestCase):
    """run() annotates concerns with commit overlap in output."""

    def test_concern_with_overlap_annotated(self):
        concern = make_event(
            "concern",
            content="Auth validation bug",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            "commit",
            content="Fix auth validation",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([concern, commit])
        output = triage_preload.run(self.smm_dir)
        self.assertIn("LIKELY ADDRESSED", output)
        self.assertIn("Fix auth validation", output)


if __name__ == "__main__":
    unittest.main()
