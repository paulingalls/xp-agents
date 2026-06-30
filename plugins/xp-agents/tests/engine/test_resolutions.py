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
from event_schema import (
    EVENT_TYPE_ANSWER,
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
)


class TestMetadataResolves(unittest.TestCase):
    """Tests for compute_resolutions() using metadata.resolves mechanism."""

    def test_goal_resolved_via_metadata_resolves(self):
        goal = make_event(EVENT_TYPE_GOAL, content="Ship v1.0")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Goal completed",
            working_on=["src/app.py"],
            metadata={"resolves": [goal["id"]]},
        )
        result = resolution.compute_resolutions([goal, resolver])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertEqual(result["goal_resolutions"][goal["id"]], resolver)
        self.assertIn(goal["id"], result["resolved_goal_ids"])

    def test_concern_resolved_via_metadata_resolves(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Missing tests")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Tests added",
            working_on=["test.py"],
            metadata={"resolves": [concern["id"]]},
        )
        result = resolution.compute_resolutions([concern, resolver])
        self.assertIn(concern["id"], result["concern_resolutions"])
        self.assertIn(concern["id"], result["resolved_concern_ids"])

    def test_debt_resolved_via_metadata_resolves(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="Hardcoded secret", files=["config.py"]
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Debt fixed",
            working_on=["config.py"],
            metadata={"resolves": [debt["id"]]},
        )
        result = resolution.compute_resolutions([debt, resolver])
        self.assertIn(debt["id"], result["debt_resolutions"])
        self.assertIn(debt["id"], result["resolved_debt_ids"])

    def test_old_references_pattern_does_not_resolve_concern(self):
        """The old pattern (references without metadata.resolves) no longer resolves."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Missing tests")
        non_resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Added tests",
            working_on=["test.py"],
            references=[concern["id"]],  # old pattern, no metadata.resolves
        )
        result = resolution.compute_resolutions([concern, non_resolver])
        self.assertNotIn(concern["id"], result["concern_resolutions"])

    def test_multiple_resolves_in_one_event(self):
        goal = make_event(EVENT_TYPE_GOAL, content="Ship v1.0")
        concern = make_event(EVENT_TYPE_CONCERN, content="Lint error")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Cleaned up",
            working_on=["app.py"],
            metadata={"resolves": [goal["id"], concern["id"]]},
        )
        result = resolution.compute_resolutions([goal, concern, resolver])
        self.assertIn(goal["id"], result["goal_resolutions"])
        self.assertIn(concern["id"], result["concern_resolutions"])

    def test_question_answer_still_works(self):
        """Question-answer linking via answer type + references is unchanged."""
        q = make_event(EVENT_TYPE_QUESTION, content="Which DB?")
        a = make_event(EVENT_TYPE_ANSWER, content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, a])
        self.assertIn(q["id"], result["question_answers"])
        self.assertIn(q["id"], result["answered_question_ids"])

    def test_question_resolved_via_metadata_resolves(self):
        """Questions can be resolved via metadata.resolves too."""
        q = make_event(EVENT_TYPE_QUESTION, content="Should Sprint replace Intent?")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Resolved: decided to keep them separate",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        result = resolution.compute_resolutions([q, resolver])
        self.assertIn(q["id"], result["question_answers"])
        self.assertIn(q["id"], result["answered_question_ids"])

    def test_question_answer_event_takes_precedence(self):
        """If both answer event and metadata.resolves exist, answer event wins."""
        q = make_event(EVENT_TYPE_QUESTION, content="Which DB?")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Resolved via housekeeping",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        answer = make_event(EVENT_TYPE_ANSWER, content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, resolver, answer])
        self.assertIn(q["id"], result["question_answers"])
        # Answer event should be the resolution, not the metadata resolver
        self.assertEqual(result["question_answers"][q["id"]], answer)

    def test_question_answer_precedence_reverse_order(self):
        """Answer event wins even if it appears before metadata.resolves."""
        q = make_event(EVENT_TYPE_QUESTION, content="Which DB?")
        answer = make_event(EVENT_TYPE_ANSWER, content="Postgres", references=[q["id"]])
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Resolved via housekeeping",
            working_on=[],
            metadata={"resolves": [q["id"]]},
        )
        result = resolution.compute_resolutions([q, answer, resolver])
        self.assertEqual(result["question_answers"][q["id"]], answer)

    def test_unresolved_items_not_in_results(self):
        goal = make_event(EVENT_TYPE_GOAL, content="Ship v1.0")
        concern = make_event(EVENT_TYPE_CONCERN, content="Missing tests")
        debt = make_event(EVENT_TYPE_DEBT, content="Tech debt", files=["old.py"])
        result = resolution.compute_resolutions([goal, concern, debt])
        self.assertEqual(len(result["goal_resolutions"]), 0)
        self.assertEqual(len(result["concern_resolutions"]), 0)
        self.assertEqual(len(result["debt_resolutions"]), 0)

    def test_resolve_only_targets_known_events(self):
        """metadata.resolves referencing unknown IDs are ignored."""
        resolver = make_event(
            EVENT_TYPE_STATUS,
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
        concern = make_event(EVENT_TYPE_CONCERN, content="Test failure")
        goal = make_event(EVENT_TYPE_GOAL, content="Fix tests")
        debt = make_event(EVENT_TYPE_DEBT, content="Legacy code", files=["old.py"])
        resolver = make_event(
            EVENT_TYPE_STATUS,
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
        assumption = make_event(EVENT_TYPE_ASSUMPTION, content="API returns JSON")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Verified: API returns JSON",
            working_on=[],
            metadata={"resolves": [assumption["id"]]},
        )
        result = resolution.compute_resolutions([assumption, resolver])
        self.assertIn(assumption["id"], result["assumption_resolutions"])
        self.assertIn(assumption["id"], result["resolved_assumption_ids"])

    def test_unresolved_assumption_not_in_results(self):
        assumption = make_event(EVENT_TYPE_ASSUMPTION, content="API returns JSON")
        result = resolution.compute_resolutions([assumption])
        self.assertEqual(len(result["assumption_resolutions"]), 0)
        self.assertEqual(len(result["resolved_assumption_ids"]), 0)

    def test_status_event_resolved_via_metadata_resolves(self):
        """Resolving a status/sprint event should be tracked (Try item refs)."""
        sprint_evt = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint completed",
            metadata={"sprint_id": "sprint-013", "action": "end"},
        )
        dropper = make_event(
            EVENT_TYPE_STATUS,
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
            EVENT_TYPE_STATUS,
            content="Some status event",
            working_on=[],
        )
        resolver = make_event(
            EVENT_TYPE_DECISION,
            content="Adopted retro Try item",
            topic="retro-try-fix",
            metadata={"resolves": [status_evt["id"]]},
        )
        result = resolution.compute_resolutions([status_evt, resolver])
        self.assertIn(status_evt["id"], result["other_resolutions"])

    def test_resolve_prefix_ambiguous_skipped(self):
        """If a prefix matches multiple events, skip it (ambiguous)."""
        c1 = make_event(EVENT_TYPE_CONCERN, content="First concern")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Second concern")
        # Force same prefix by overwriting IDs
        shared = "abcdef12"
        c1["id"] = shared + "-0000-0000-0000-000000000001"
        c2["id"] = shared + "-0000-0000-0000-000000000002"
        resolver = make_event(
            EVENT_TYPE_STATUS,
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
            EVENT_TYPE_STATUS,
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
            EVENT_TYPE_DECISION,
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
        concern = make_event(EVENT_TYPE_CONCERN, content="Real concern")
        concern["id"] = shared_id
        # Retro with a try whose id collides
        retro = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Session retrospective",
            **{"try": [{"id": shared_id, "content": "Phantom try", "event_refs": []}]},
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
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
        q = make_event(EVENT_TYPE_QUESTION, content="Which DB?")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Stale question: blocking question unanswered",
            references=[q["id"]],
        )
        answer = make_event(EVENT_TYPE_ANSWER, content="Postgres", references=[q["id"]])
        result = resolution.compute_resolutions([q, flag, answer])
        self.assertIn(flag["id"], result["resolved_concern_ids"])
        self.assertEqual(result["concern_resolutions"][flag["id"]], answer)

    def test_concern_cascade_closes_when_referenced_decision_resolved(self):
        decision = make_event(EVENT_TYPE_DECISION, content="Use JWT", topic="auth")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Superseded decision on auth",
            references=[decision["id"]],
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Decision explicitly retired",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        result = resolution.compute_resolutions([decision, flag, resolver])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_no_cascade_when_target_unresolved(self):
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="References an event that never resolves",
            references=["deadbeef0000"],
        )
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_handles_multiple_references_or_semantics(self):
        a = make_event(EVENT_TYPE_QUESTION, content="A?")
        b = make_event(EVENT_TYPE_QUESTION, content="B?")
        flag = make_event(
            EVENT_TYPE_CONCERN,
            content="Flag referencing A and B",
            references=[a["id"], b["id"]],
        )
        # Only A resolves; flag still closes (ANY referenced id resolving is enough).
        answer_a = make_event(
            EVENT_TYPE_ANSWER, content="A answered", references=[a["id"]]
        )
        result = resolution.compute_resolutions([a, b, flag, answer_a])
        self.assertIn(flag["id"], result["resolved_concern_ids"])

    def test_cascade_extends_to_multi_level(self):
        """A two-level flag chain (B → A → resolved root) closes BOTH levels.

        The cascade iterates to a fixed point: A closes referencing the
        resolved question, is fed back into the resolver set, then B closes
        referencing the now-resolved A on the next pass.
        """
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        c_inner = make_event(EVENT_TYPE_CONCERN, content="inner", references=[q["id"]])
        c_outer = make_event(
            EVENT_TYPE_CONCERN, content="outer", references=[c_inner["id"]]
        )
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        result = resolution.compute_resolutions([q, c_inner, c_outer, answer])
        # Inner cascades closed (references a resolved question).
        self.assertIn(c_inner["id"], result["resolved_concern_ids"])
        # Outer ALSO cascades closed — the fixed-point loop extends multi-level.
        self.assertIn(c_outer["id"], result["resolved_concern_ids"])

    def test_cascade_two_level_flag_chain_concern_root(self):
        """E2E flag-cascade shape: a root concern resolved via metadata.resolves,
        flag A referencing the root, flag B referencing flag A. Both flags close.

        Mirrors the production shape (retro/reviewer flags wire
        references=[root_id]); the integration E2E pins the single-level case,
        this pins the two-level extension at the engine boundary.
        """
        root = make_event(EVENT_TYPE_CONCERN, content="root concern: stop hook broken")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="resolved: stop hook fixed",
            working_on=["hook.py"],
            metadata={"resolves": [root["id"]]},
        )
        flag_a = make_event(
            EVENT_TYPE_CONCERN, content="flag A", references=[root["id"]]
        )
        flag_b = make_event(
            EVENT_TYPE_CONCERN, content="flag B", references=[flag_a["id"]]
        )
        result = resolution.compute_resolutions([root, resolver, flag_a, flag_b])
        resolved = result["resolved_concern_ids"]
        self.assertIn(root["id"], resolved)
        self.assertIn(flag_a["id"], resolved)
        self.assertIn(flag_b["id"], resolved)

    def test_cascade_extends_to_three_levels(self):
        """Three-level chain (C → B → A → resolved root) closes every level."""
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        a = make_event(EVENT_TYPE_CONCERN, content="A", references=[q["id"]])
        b = make_event(EVENT_TYPE_CONCERN, content="B", references=[a["id"]])
        c = make_event(EVENT_TYPE_CONCERN, content="C", references=[b["id"]])
        answer = make_event(EVENT_TYPE_ANSWER, content="answered", references=[q["id"]])
        result = resolution.compute_resolutions([q, a, b, c, answer])
        self.assertIn(a["id"], result["resolved_concern_ids"])
        self.assertIn(b["id"], result["resolved_concern_ids"])
        self.assertIn(c["id"], result["resolved_concern_ids"])

    def test_cascade_cycle_terminates_and_leaves_unresolved(self):
        """A reference cycle (B → A → B) with no path to a resolved root
        terminates without hanging and leaves both events unresolved."""
        a = make_event(EVENT_TYPE_CONCERN, content="A")
        b = make_event(EVENT_TYPE_CONCERN, content="B")
        a["references"] = [b["id"]]
        b["references"] = [a["id"]]
        result = resolution.compute_resolutions([a, b])
        self.assertNotIn(a["id"], result["resolved_concern_ids"])
        self.assertNotIn(b["id"], result["resolved_concern_ids"])

    def test_cascade_does_not_relay_through_enrichment_status(self):
        """KNOWN RISK pin (SMM assumption d0eac70ea560).

        `post_tool_use.py` attaches `references` to status events as semantic
        enrichment (status → related decision). When that decision is resolved,
        the status event itself cascade-closes — but it lands in
        `other_resolutions` and is NOT fed back as a relay. So a substantive
        concern that merely references such an enrichment-resolved status event
        does NOT cascade-close. This preserves single-level behavior as the
        floor: multi-level closure propagates only through genuine flag/tracked
        chains (concern/goal/debt/decision/assumption/question), never through
        ephemeral status hops. Deliberate, tested decision — not an accident.
        """
        decision = make_event(EVENT_TYPE_DECISION, content="Use JWT", topic="auth")
        # Enrichment status: references the decision (mirrors post_tool_use refs).
        status = make_event(
            EVENT_TYPE_STATUS,
            content="Edited auth module",
            working_on=["auth.py"],
            references=[decision["id"]],
        )
        # The decision is explicitly resolved.
        decision_resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Decision retired",
            working_on=[],
            metadata={"resolves": [decision["id"]]},
        )
        # A substantive concern that contextually references the status event.
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Substantive concern referencing a status event",
            references=[status["id"]],
        )
        result = resolution.compute_resolutions(
            [decision, status, decision_resolver, concern]
        )
        # The enrichment status itself still cascade-resolves (single-level,
        # unchanged behavior) — it lands in the "other" bucket.
        self.assertIn(status["id"], result["resolved_other_ids"])
        # But the substantive concern does NOT close — no relay through status.
        self.assertNotIn(concern["id"], result["resolved_concern_ids"])

    def test_cascade_self_reference_is_no_op(self):
        flag = make_event(EVENT_TYPE_CONCERN, content="self-ref")
        flag["references"] = [flag["id"]]
        result = resolution.compute_resolutions([flag])
        self.assertNotIn(flag["id"], result["resolved_concern_ids"])

    def test_question_two_hops_from_resolved_root_stays_open(self):
        """A question never cascade-closes, even via a multi-hop reference chain.

        A question whose `references` transitively reach a resolved root (here:
        question → concern → resolved root question) must stay OPEN — it clears
        ONLY via an answer event, metadata.resolves, or AskUserQuestion (the
        blocking-question gate). Auto-closing it via cascade would fabricate a
        customer decision, drop it from the open-questions nudge, and inflate
        retro questions_answered.
        """
        root = make_event(EVENT_TYPE_QUESTION, content="root question")
        answer = make_event(
            EVENT_TYPE_ANSWER, content="answered", references=[root["id"]]
        )
        # A concern one hop from the resolved root (legitimately cascades closed).
        bridge = make_event(
            EVENT_TYPE_CONCERN, content="bridge concern", references=[root["id"]]
        )
        # A genuinely-open question two hops out, pointing at the bridge concern.
        open_q = make_event(
            EVENT_TYPE_QUESTION,
            content="still-open question",
            references=[bridge["id"]],
        )
        result = resolution.compute_resolutions([root, answer, bridge, open_q])
        # Root is answered; bridge concern cascades closed.
        self.assertIn(root["id"], result["answered_question_ids"])
        self.assertIn(bridge["id"], result["resolved_concern_ids"])
        # The second-hop question stays OPEN — questions never cascade-close.
        self.assertNotIn(open_q["id"], result["answered_question_ids"])
        self.assertNotIn(open_q["id"], result["question_answers"])

    def test_question_one_hop_from_resolved_root_stays_open(self):
        """Even a single-hop question does not cascade-close — only the
        main-pass paths (answer / metadata.resolves) clear a question."""
        root = make_event(EVENT_TYPE_DECISION, content="settled", topic="x")
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="retired",
            working_on=[],
            metadata={"resolves": [root["id"]]},
        )
        q = make_event(
            EVENT_TYPE_QUESTION, content="dependent question", references=[root["id"]]
        )
        result = resolution.compute_resolutions([root, resolver, q])
        self.assertIn(root["id"], result["resolved_decision_ids"])
        self.assertNotIn(q["id"], result["answered_question_ids"])

    def test_cascade_respects_event_type_buckets(self):
        """A goal with references to a resolved event lands in goal_resolutions."""
        q = make_event(EVENT_TYPE_QUESTION, content="root")
        g = make_event(EVENT_TYPE_GOAL, content="dependent goal", references=[q["id"]])
        answer = make_event(EVENT_TYPE_ANSWER, content="resolved", references=[q["id"]])
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
            EVENT_TYPE_QUESTION,
            content="A blocking question",
            priority=PRIORITY_BLOCKING,
        )
        decision = make_event(
            EVENT_TYPE_DECISION,
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
