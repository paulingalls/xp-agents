#!/usr/bin/env python3
"""Tests for resolution logic and event reading.

Split from test_parse.py — covers TestMetadataResolves, TestReadEventsFrom.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
import read_delta
import resolution
from _lock_helpers import held_events_lock
from conftest import _SMMTestCase, make_event, make_retrospective_with_try


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
        result = resolution.compute_resolutions([goal, resolver])
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
        result = resolution.compute_resolutions([concern, resolver])
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
        result = resolution.compute_resolutions([debt, resolver])
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
        result = resolution.compute_resolutions([concern, non_resolver])
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
        result = resolution.compute_resolutions([goal, concern, resolver])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertIn(concern["id"], result["concern_resolutions"])

    def test_question_answer_still_works(self):
        """Question-answer linking via answer type + references is unchanged."""
        q = make_event("question", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, a])
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
        result = resolution.compute_resolutions([q, resolver])
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
        result = resolution.compute_resolutions([q, resolver, answer])
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
        result = resolution.compute_resolutions([q, answer, resolver])
        self.assertEqual(result["question_answers"][q["id"]], answer)

    def test_unresolved_items_not_in_results(self):
        goal = make_event("goal", content="Ship v1.0")
        concern = make_event("concern", content="Missing tests")
        debt = make_event("debt", content="Tech debt", files=["old.py"])
        result = resolution.compute_resolutions([goal, concern, debt])
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
        result = resolution.compute_resolutions([resolver])
        self.assertEqual(len(result["goal_resolutions"]), 0)
        self.assertEqual(len(result["concern_resolutions"]), 0)
        self.assertEqual(len(result["debt_resolutions"]), 0)

    def test_resolve_via_full_id(self):
        """metadata.resolves with full 12-char ID matches exactly."""
        concern = make_event("concern", content="Test failure")
        goal = make_event("goal", content="Fix tests")
        debt = make_event("debt", content="Legacy code", files=["old.py"])
        resolver = make_event(
            "status",
            content="All fixed",
            working_on=[],
            metadata={
                "resolves": [
                    concern["id"],
                    goal["id"],
                    debt["id"],
                ]
            },
        )
        result = resolution.compute_resolutions([concern, goal, debt, resolver])
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
        result = resolution.compute_resolutions([assumption, resolver])
        self.assertIn(assumption["id"], result["assumption_resolutions"])
        self.assertIn(assumption["id"], result["resolved_assumption_ids"])

    def test_unresolved_assumption_not_in_results(self):
        assumption = make_event("assumption", content="API returns JSON")
        result = resolution.compute_resolutions([assumption])
        self.assertEqual(len(result["assumption_resolutions"]), 0)
        self.assertEqual(len(result["resolved_assumption_ids"]), 0)

    def test_status_event_resolved_via_metadata_resolves(self):
        """Resolving a status/sprint event should be tracked (Try item refs)."""
        sprint_evt = make_event(
            "sprint",
            content="Sprint completed",
            metadata={"sprint_id": "sprint-013", "action": "end"},
        )
        dropper = make_event(
            "status",
            content="Dropped retro Try: truncated UUID bug already fixed",
            working_on=[],
            metadata={"resolves": [sprint_evt["id"]], "disposition": "dropped"},
        )
        result = resolution.compute_resolutions([sprint_evt, dropper])
        self.assertIn(sprint_evt["id"], result["other_resolutions"])
        self.assertIn(sprint_evt["id"], result["resolved_other_ids"])

    def test_other_resolution_includes_disposition(self):
        """Resolutions of non-standard types preserve metadata like disposition."""
        status_evt = make_event(
            "status",
            content="Some status event",
            working_on=[],
        )
        resolver = make_event(
            "decision",
            content="Adopted retro Try item",
            topic="retro-try-fix",
            metadata={"resolves": [status_evt["id"]]},
        )
        result = resolution.compute_resolutions([status_evt, resolver])
        self.assertIn(status_evt["id"], result["other_resolutions"])

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
        result = resolution.compute_resolutions([c1, c2, resolver])
        # Ambiguous — neither should be resolved
        self.assertEqual(len(result["concern_resolutions"]), 0)


class TestRetroTryResolution(unittest.TestCase):
    """Try items live nested inside retrospective.try[]. compute_resolutions
    must index those nested IDs so disposition events (adopt/defer/drop)
    that target a Try via metadata.resolves resolve correctly. Without this,
    every drop/defer is silently dropped and the retro analyst re-proposes
    Tries that the user already acted on.
    """

    def test_compute_resolutions_resolves_try_id_nested_in_retrospective(self):
        retro = make_retrospective_with_try("a1b2c3d4e5f6", "Adopt commit-after-green")
        dropper = make_event(
            "status",
            content="Dropped retro Try",
            working_on=[],
            metadata={"resolves": ["a1b2c3d4e5f6"], "disposition": "dropped"},
        )
        result = resolution.compute_resolutions([retro, dropper])
        self.assertIn("a1b2c3d4e5f6", result["other_resolutions"])
        self.assertEqual(result["other_resolutions"]["a1b2c3d4e5f6"], dropper)
        self.assertIn("a1b2c3d4e5f6", result["resolved_other_ids"])

    def test_compute_resolutions_resolves_try_id_via_decision_adopt(self):
        retro = make_retrospective_with_try("b2c3d4e5f6a1", "Adopt fairness batch")
        adopter = make_event(
            "decision",
            content="Adopting retro Try fairness batch",
            topic="retro-try-fairness",
            metadata={"resolves": ["b2c3d4e5f6a1"]},
        )
        result = resolution.compute_resolutions([retro, adopter])
        self.assertIn("b2c3d4e5f6a1", result["other_resolutions"])

    def test_top_level_event_id_takes_precedence_over_try_id_collision(self):
        """If a Try id collides with a real top-level event id (extremely rare),
        the top-level event wins. Resolution targets the real event."""
        shared_id = "c3d4e5f6a1b2"
        # Top-level concern with the colliding ID
        concern = make_event("concern", content="Real concern")
        concern["id"] = shared_id
        # Retro with a try whose id collides
        retro = make_event(
            "retrospective",
            content="Session retrospective",
            **{"try": [{"id": shared_id, "content": "Phantom try", "event_refs": []}]},
        )
        resolver = make_event(
            "status",
            content="Resolved",
            working_on=[],
            metadata={"resolves": [shared_id]},
        )
        result = resolution.compute_resolutions([concern, retro, resolver])
        # Top-level concern bucket gets it; "other" does not
        self.assertIn(shared_id, result["concern_resolutions"])
        self.assertNotIn(shared_id, result["other_resolutions"])

    def test_unresolved_try_id_not_in_results(self):
        """A retro with a Try and no resolver leaves the Try unresolved."""
        retro = make_retrospective_with_try("d4e5f6a1b2c3", "Untouched try")
        result = resolution.compute_resolutions([retro])
        self.assertNotIn("d4e5f6a1b2c3", result["other_resolutions"])
        self.assertNotIn("d4e5f6a1b2c3", result["resolved_other_ids"])


class TestCascadeResolution(unittest.TestCase):
    """Cascade pass: events whose top-level `references` list points at a
    resolved id are themselves cascade-closed. WEAK link — complements
    metadata.resolves (STRONG).
    """

    def test_concern_cascade_closes_when_referenced_question_answered(self):
        q = make_event("question", content="Which DB?")
        flag = make_event(
            "concern",
            content="Stale question: blocking question unanswered",
            references=[q["id"]],
        )
        answer = make_event("answer", content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, flag, answer])
        self.assertIn(flag["id"], result["resolved_concern_ids"])
        self.assertEqual(result["concern_resolutions"][flag["id"]], answer)

    def test_concern_cascade_closes_when_referenced_decision_resolved(self):
        decision = make_event("decision", content="Use JWT", topic="auth")
        flag = make_event(
            "concern",
            content="Superseded decision on auth",
            references=[decision["id"]],
        )
        resolver = make_event(
            "status",
            content="Decision explicitly retired",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        result = resolution.compute_resolutions([decision, flag, resolver])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_no_cascade_when_target_unresolved(self):
        flag = make_event(
            "concern",
            content="References an event that never resolves",
            references=["deadbeef0000"],
        )
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_handles_multiple_references_or_semantics(self):
        a = make_event("question", content="A?")
        b = make_event("question", content="B?")
        flag = make_event(
            "concern",
            content="Flag referencing A and B",
            references=[a["id"], b["id"]],
        )
        # Only A resolves; flag still closes (ANY referenced id resolving is enough).
        answer_a = make_event("answer", content="A answered", references=[a["id"]])
        result = resolution.compute_resolutions([a, b, flag, answer_a])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_is_single_level_only(self):
        q = make_event("question", content="root")
        c_inner = make_event("concern", content="inner", references=[q["id"]])
        c_outer = make_event("concern", content="outer", references=[c_inner["id"]])
        answer = make_event("answer", content="answered", references=[q["id"]])
        result = resolution.compute_resolutions([q, c_inner, c_outer, answer])
        # Inner cascades closed (references a resolved question).
        self.assertIn(c_inner["id"], result["resolved_concern_ids"])
        # Outer does NOT cascade closed — cascade is one-level by design.
        self.assertNotIn(c_outer["id"], result["resolved_concern_ids"])

    def test_cascade_self_reference_is_no_op(self):
        flag = make_event("concern", content="self-ref")
        flag["references"] = [flag["id"]]
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_respects_event_type_buckets(self):
        """A goal with references to a resolved event lands in goal_resolutions."""
        q = make_event("question", content="root")
        g = make_event("goal", content="dependent goal", references=[q["id"]])
        answer = make_event("answer", content="resolved", references=[q["id"]])
        result = resolution.compute_resolutions([q, g, answer])
        self.assertIn(g["id"], result["resolved_goal_ids"])
        self.assertNotIn(g["id"], result["resolved_concern_ids"])


class TestReadEventsFrom(_SMMTestCase):
    def test_raises_on_lock_timeout(self):
        """read_events_from should raise LockTimeoutError, not silently degrade."""
        self._write_events([make_event()])
        with (
            held_events_lock(self.smm_dir),
            self.assertRaises(_append_impl.LockTimeoutError),
        ):
            read_delta.read_events_from(self.smm_dir, 0)

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


class TestMetadataResolvesEndToEnd(unittest.TestCase):
    """E2E pin for the bug behind story-005: a question event resolved
    by a list-shaped metadata.resolves must be detected as answered,
    so the stale-question concern detector at concerns.py:314 does
    NOT flag it. The original bug (decision 311a2af6fce7) emitted
    metadata.resolves as a string scalar instead of a list — the
    cascade silently failed and a stale-question flag fired anyway.
    """

    def test_blocking_question_resolved_by_list_metadata_resolves(self):
        import concerns
        from event_schema import PRIORITY_BLOCKING

        question = make_event(
            "question",
            content="A blocking question",
            priority=PRIORITY_BLOCKING,
        )
        decision = make_event(
            "decision",
            topic="answer",
            content="Decision answering the question",
            metadata={"resolves": [question["id"]]},
        )
        events = [question, decision] + [
            make_event(content=f"filler {i}") for i in range(25)
        ]

        result = resolution.compute_resolutions(events)
        self.assertIn(
            question["id"],
            result["answered_question_ids"],
            "STRONG resolution via list metadata.resolves must mark"
            " the question as answered",
        )

        raised = concerns.detect_conflicts(events, agent_id="main")
        stale_flags = [c for c in raised if "Stale question" in c["content"]]
        self.assertEqual(
            stale_flags,
            [],
            f"Stale-question detector must not flag a properly-resolved"
            f" blocking question; got: {stale_flags}",
        )


if __name__ == "__main__":
    unittest.main()
