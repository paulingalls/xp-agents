#!/usr/bin/env python3
"""Tests for resolution logic and event reading.

Split from test_parse.py — covers TestMetadataResolves, TestReadEventsFrom.
"""

import fcntl
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
import materialize
import read_delta
from conftest import _SMMTestCase, make_event


class TestMetadataResolves(unittest.TestCase):
    """Tests for compute_resolutions() using metadata.resolves mechanism."""

    def test_goal_resolved_via_metadata_resolves(self):
        goal = make_event("goal", content="Ship v1.0")
        resolver = make_event(
            "status",
            content="Goal completed",
            working_on=["src/app.py"],
            metadata={"resolves": [goal["id"]]},
        )
        result = _append_impl.compute_resolutions([goal, resolver])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertEqual(result["goal_resolutions"][goal["id"]], resolver)
        self.assertIn(goal["id"], result["resolved_goal_ids"])

    def test_concern_resolved_via_metadata_resolves(self):
        concern = make_event("concern", content="Missing tests")
        resolver = make_event(
            "status",
            content="Tests added",
            working_on=["test.py"],
            metadata={"resolves": [concern["id"]]},
        )
        result = _append_impl.compute_resolutions([concern, resolver])
        self.assertIn(concern["id"], result["concern_resolutions"])
        self.assertIn(concern["id"], result["resolved_concern_ids"])

    def test_debt_resolved_via_metadata_resolves(self):
        debt = make_event("debt", content="Hardcoded secret", files=["config.py"])
        resolver = make_event(
            "status",
            content="Debt fixed",
            working_on=["config.py"],
            metadata={"resolves": [debt["id"]]},
        )
        result = _append_impl.compute_resolutions([debt, resolver])
        self.assertIn(debt["id"], result["debt_resolutions"])
        self.assertIn(debt["id"], result["resolved_debt_ids"])

    def test_old_references_pattern_does_not_resolve_concern(self):
        """The old pattern (references without metadata.resolves) no longer resolves."""
        concern = make_event("concern", content="Missing tests")
        non_resolver = make_event(
            "status",
            content="Added tests",
            working_on=["test.py"],
            references=[concern["id"]],  # old pattern, no metadata.resolves
        )
        result = _append_impl.compute_resolutions([concern, non_resolver])
        self.assertNotIn(concern["id"], result["concern_resolutions"])

    def test_multiple_resolves_in_one_event(self):
        goal = make_event("goal", content="Ship v1.0")
        concern = make_event("concern", content="Lint error")
        resolver = make_event(
            "status",
            content="Cleaned up",
            working_on=["app.py"],
            metadata={"resolves": [goal["id"], concern["id"]]},
        )
        result = _append_impl.compute_resolutions([goal, concern, resolver])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertIn(concern["id"], result["concern_resolutions"])

    def test_question_answer_still_works(self):
        """Question-answer linking via answer type + references is unchanged."""
        q = make_event("question", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        result = _append_impl.compute_resolutions([q, a])
        self.assertIn(q["id"], result["question_answers"])
        self.assertIn(q["id"], result["answered_question_ids"])

    def test_question_resolved_via_metadata_resolves(self):
        """Questions can be resolved via metadata.resolves too."""
        q = make_event("question", content="Should Sprint replace Intent?")
        resolver = make_event(
            "status",
            content="Resolved: decided to keep them separate",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        result = _append_impl.compute_resolutions([q, resolver])
        self.assertIn(q["id"], result["question_answers"])
        self.assertIn(q["id"], result["answered_question_ids"])

    def test_question_answer_event_takes_precedence(self):
        """If both answer event and metadata.resolves exist, answer event wins."""
        q = make_event("question", content="Which DB?")
        resolver = make_event(
            "status",
            content="Resolved via housekeeping",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        answer = make_event("answer", content="Postgres", references=[q["id"]])
        result = _append_impl.compute_resolutions([q, resolver, answer])
        self.assertIn(q["id"], result["question_answers"])
        # Answer event should be the resolution, not the metadata resolver
        self.assertEqual(result["question_answers"][q["id"]], answer)

    def test_question_answer_precedence_reverse_order(self):
        """Answer event wins even if it appears before metadata.resolves."""
        q = make_event("question", content="Which DB?")
        answer = make_event("answer", content="Postgres", references=[q["id"]])
        resolver = make_event(
            "status",
            content="Resolved via housekeeping",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        result = _append_impl.compute_resolutions([q, answer, resolver])
        self.assertEqual(result["question_answers"][q["id"]], answer)

    def test_unresolved_items_not_in_results(self):
        goal = make_event("goal", content="Ship v1.0")
        concern = make_event("concern", content="Missing tests")
        debt = make_event("debt", content="Tech debt", files=["old.py"])
        result = _append_impl.compute_resolutions([goal, concern, debt])
        self.assertEqual(len(result["goal_resolutions"]), 0)
        self.assertEqual(len(result["concern_resolutions"]), 0)
        self.assertEqual(len(result["debt_resolutions"]), 0)

    def test_resolve_only_targets_known_events(self):
        """metadata.resolves referencing unknown IDs are ignored."""
        resolver = make_event(
            "status",
            content="Fixed stuff",
            working_on=["app.py"],
            metadata={"resolves": ["nonexistent-id"]},
        )
        result = _append_impl.compute_resolutions([resolver])
        self.assertEqual(len(result["goal_resolutions"]), 0)
        self.assertEqual(len(result["concern_resolutions"]), 0)
        self.assertEqual(len(result["debt_resolutions"]), 0)

    def test_resolve_via_short_id_prefix(self):
        """metadata.resolves with 8-char prefix should match full UUID."""
        concern = make_event("concern", content="Test failure")
        goal = make_event("goal", content="Fix tests")
        debt = make_event("debt", content="Legacy code", files=["old.py"])
        resolver = make_event(
            "status",
            content="All fixed",
            working_on=[],
            metadata={
                "resolves": [
                    concern["id"][:8],
                    goal["id"][:8],
                    debt["id"][:8],
                ]
            },
        )
        result = _append_impl.compute_resolutions([concern, goal, debt, resolver])
        self.assertIn(concern["id"], result["concern_resolutions"])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertIn(debt["id"], result["debt_resolutions"])

    def test_assumption_resolved_via_metadata_resolves(self):
        assumption = make_event("assumption", content="API returns JSON")
        resolver = make_event(
            "status",
            content="Verified: API returns JSON",
            working_on=[],
            metadata={"resolves": [assumption["id"]]},
        )
        result = _append_impl.compute_resolutions([assumption, resolver])
        self.assertIn(assumption["id"], result["assumption_resolutions"])
        self.assertIn(assumption["id"], result["resolved_assumption_ids"])

    def test_unresolved_assumption_not_in_results(self):
        assumption = make_event("assumption", content="API returns JSON")
        result = _append_impl.compute_resolutions([assumption])
        self.assertEqual(len(result["assumption_resolutions"]), 0)
        self.assertEqual(len(result["resolved_assumption_ids"]), 0)

    def test_resolve_prefix_ambiguous_skipped(self):
        """If a prefix matches multiple events, skip it (ambiguous)."""
        c1 = make_event("concern", content="First concern")
        c2 = make_event("concern", content="Second concern")
        # Force same prefix by overwriting IDs
        shared = "abcdef12"
        c1["id"] = shared + "-0000-0000-0000-000000000001"
        c2["id"] = shared + "-0000-0000-0000-000000000002"
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [shared]},
        )
        result = _append_impl.compute_resolutions([c1, c2, resolver])
        # Ambiguous — neither should be resolved
        self.assertEqual(len(result["concern_resolutions"]), 0)


class TestBuildIndicesResolutions(_SMMTestCase):
    """Tests that build_indices() populates goal/debt resolution indices."""

    def test_goal_resolutions_in_indices(self):
        goal = make_event("goal", content="Ship v1.0")
        resolver = make_event(
            "status",
            content="Done",
            working_on=["app.py"],
            metadata={"resolves": [goal["id"]]},
        )
        indices = materialize.build_indices([goal, resolver])
        self.assertIn(goal["id"], indices["goal_resolutions"])

    def test_decision_resolutions_in_indices(self):
        decision = make_event("decision", content="Use Redis", topic="caching")
        resolver = make_event(
            "status",
            content="Confirmed",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        indices = materialize.build_indices([decision, resolver])
        self.assertIn(decision["id"], indices["decision_resolutions"])

    def test_debt_resolutions_in_indices(self):
        debt = make_event("debt", content="Legacy code", files=["old.py"])
        resolver = make_event(
            "status",
            content="Refactored",
            working_on=["old.py"],
            metadata={"resolves": [debt["id"]]},
        )
        indices = materialize.build_indices([debt, resolver])
        self.assertIn(debt["id"], indices["debt_resolutions"])

    def test_concern_resolution_uses_metadata_resolves(self):
        """build_indices concern_resolutions uses metadata.resolves, not references."""
        concern = make_event("concern", content="Bug found")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=["fix.py"],
            metadata={"resolves": [concern["id"]]},
        )
        indices = materialize.build_indices([concern, resolver])
        self.assertIn(concern["id"], indices["concern_resolutions"])


class TestReadEventsFrom(_SMMTestCase):
    def test_raises_on_lock_timeout(self):
        """read_events_from should raise LockTimeoutError, not silently degrade."""
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_fd = open(lock_file, "a")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with self.assertRaises(_append_impl.LockTimeoutError):
                read_delta.read_events_from(self.smm_dir, 0)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def test_reads_all_from_0(self):
        self._write_events([make_event(), make_event()])
        events, total = read_delta.read_events_from(self.smm_dir, 0)
        self.assertEqual(len(events), 2)
        self.assertEqual(total, 2)

    def test_reads_from_offset(self):
        self._write_events(
            [
                make_event(content="first"),
                make_event(content="second"),
            ]
        )
        events, total = read_delta.read_events_from(self.smm_dir, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "second")
        self.assertEqual(total, 2)

    def test_offset_beyond_end(self):
        self._write_events([make_event()])
        events, total = read_delta.read_events_from(self.smm_dir, 100)
        self.assertEqual(len(events), 0)
        self.assertEqual(total, 1)

    def test_missing_file(self):
        self.events_file.unlink()
        events, total = read_delta.read_events_from(self.smm_dir, 0)
        self.assertEqual(len(events), 0)
        self.assertEqual(total, 0)

    def test_malformed_lines_skipped(self):
        self._write_raw_lines(
            [
                json.dumps(make_event()),
                "not json",
                json.dumps(make_event()),
            ]
        )
        events, total = read_delta.read_events_from(self.smm_dir, 0)
        self.assertEqual(len(events), 2)
        self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
