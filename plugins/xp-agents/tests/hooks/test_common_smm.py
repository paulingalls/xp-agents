#!/usr/bin/env python3
"""Tests for SMM event reading, decision finding, and conflict detection.

Split from test_common.py. Lookup/utility tests moved to test_common_smm_lookups.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import concerns
from conftest import _HookTestCase, make_event


class TestReadEventsRaw(_HookTestCase):
    def test_reads_valid_events(self):
        events = [make_event(), make_event("status")]
        self._write_events(events)
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_skips_malformed_lines(self):
        self._write_raw_lines(
            [json.dumps(make_event()), "bad line", json.dumps(make_event())]
        )
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_empty_file(self):
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])

    def test_missing_file(self):
        self.events_file.unlink()
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])


class TestFindRelatedDecisions(unittest.TestCase):
    """Test concerns.find_related_decisions correctness."""

    def test_matches_via_working_on(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "/tmp/src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_no_match_different_file(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "/tmp/src/other.ts", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_no_substring_false_positive_via_references(self):
        """'a.py' must not match a reference to 'data.py'."""
        d = make_event(
            "decision",
            topic="naming",
            content="Naming convention",
            references=["data.py"],
        )
        result = concerns.find_related_decisions([d], "a.py", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_exact_reference_match(self):
        """Exact normalized path in references should match."""
        d = make_event(
            "decision", topic="auth", content="Use JWT", references=["src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_skips_non_decision_events(self):
        s = make_event("status", content="Working", working_on=["/tmp/src/app.ts"])
        result = concerns.find_related_decisions([s], "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_invalid_agent_id_graceful(self):
        """Invalid agent_id in _validate_agent_id should not crash hooks."""
        import post_tool_use
        from conftest import _make_write_input

        result = post_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "x.py", "content": "x"},
                agent_id="bad;agent",
            ),
        )
        self.assertIsNone(result)


class TestDetectConflictsCommon(_HookTestCase):
    """Test detect_conflicts after extraction to concerns.py."""

    def test_import_from_concerns(self):
        self.assertTrue(hasattr(concerns, "detect_conflicts"))
        self.assertTrue(hasattr(concerns, "make_concern"))

    def test_overlapping_working_on(self):
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        self.assertTrue(any("overlap" in c["content"].lower() for c in found))

    def test_no_overlap_different_file(self):
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/other.ts"]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_empty_working_on_clears_overlap(self):
        """working_on=[] should clear agent's file list."""
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
            make_event("status", agent_id="other", working_on=[]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_stale_question_detected(self):
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        self.assertTrue(any("stale" in c["content"].lower() for c in found))

    def test_without_file_path_skips_pattern_1(self):
        """When file_path=None, skip overlapping working_on check."""
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
        ]
        found = concerns.detect_conflicts(events, "main")
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_without_file_path_runs_other_patterns(self):
        """Patterns 2-5 still run when file_path=None."""
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        found = concerns.detect_conflicts([a, d], "main")
        self.assertTrue(any("contradict" in c["content"].lower() for c in found))

    def test_superseded_decision(self):
        events = [
            make_event("decision", topic="db", content="Use Postgres"),
            make_event("decision", topic="db", content="Use MySQL"),
        ]
        found = concerns.detect_conflicts(events, "main")
        self.assertTrue(any("superseded" in c["content"].lower() for c in found))

    def test_convention_violation(self):
        events = [
            make_event("convention", topic="naming", content="Use camelCase"),
            make_event("decision", topic="naming", content="Use snake_case"),
        ]
        found = concerns.detect_conflicts(events, "main")
        self.assertTrue(any("convention" in c["content"].lower() for c in found))

    def test_no_duplicate_convention_violation(self):
        """Should not re-generate concern if one already exists for same conflict."""
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event("decision", topic="naming", content="Use snake_case")
        existing_concern = make_event(
            "concern",
            content="Convention violation: decision on 'naming' "
            "diverges from established convention.",
        )
        events = [conv, dec, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 0)

    def test_supersedes_metadata_skips_concern(self):
        """metadata.supersedes referencing the prior decision suppresses pattern #5."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event(
            "decision",
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_supersedes_metadata_full_id_matches(self):
        """Full 12-char ID in supersedes matches exactly."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event(
            "decision",
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": [d1["id"]]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_supersedes_metadata_wrong_id_still_fires(self):
        """Bogus nonexistent ID in supersedes does NOT silence the check."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event(
            "decision",
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": ["deadbeef12345678"]},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_supersedes_metadata_empty_array_still_fires(self):
        """Empty supersedes array means no explicit override — concern still raised."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event(
            "decision",
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": []},
        )
        found = concerns.detect_conflicts([d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_assumption_contradicted_concern_references_assumption(self):
        """Flag concern references the assumption event it flags (WEAK link)."""
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        self.assertEqual(flag.get("references"), [a["id"]])

    def test_assumption_contradicted_within_budget(self):
        """Assumption contradicted concern must stay within 400-char budget."""
        from event_schema import CONTENT_BUDGETS

        a = make_event("assumption", content="x" * 300)
        d = make_event("discovery", content="y" * 300, references=[a["id"]])
        found = concerns.detect_conflicts([a, d], "main")
        flag = next(c for c in found if "contradict" in c["content"].lower())
        budget = CONTENT_BUDGETS["concern"]
        self.assertLessEqual(
            len(flag["content"]),
            budget,
            f"concern content {len(flag['content'])} exceeds {budget}",
        )

    def test_convention_violation_concern_references_conventions(self):
        """Flag concern references the topic's convention ids."""
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event("decision", topic="naming", content="Use snake_case")
        found = concerns.detect_conflicts([conv, dec], "main")
        flag = next(c for c in found if "convention" in c["content"].lower())
        self.assertEqual(flag.get("references"), [conv["id"]])

    def test_stale_question_concern_references_question(self):
        """Flag concern references the stale question id (WEAK link)."""
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "stale" in c["content"].lower())
        self.assertEqual(flag.get("references"), [q["id"]])

    def test_superseded_decision_concern_references_prior_decision(self):
        """Flag concern references the older (superseded) decision id."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event("decision", topic="db", content="Use MySQL")
        found = concerns.detect_conflicts([d1, d2], "main")
        flag = next(c for c in found if "superseded" in c["content"].lower())
        self.assertEqual(flag.get("references"), [d1["id"]])

    def test_overlapping_working_on_concern_has_no_references(self):
        """Pattern 1 references an agent_id, not an event id — no refs attached."""
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "overlap" in c["content"].lower())
        self.assertFalse(flag.get("references"))

    def test_supersedes_metadata_different_topic_still_fires(self):
        """supersedes must reference the same-topic predecessor, not any decision."""
        d_other = make_event(
            "decision", topic="api", content="Use REST"
        )  # different topic
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event(
            "decision",
            topic="db",
            content="Use MySQL",
            metadata={"supersedes": [d_other["id"]]},  # wrong topic reference
        )
        found = concerns.detect_conflicts([d_other, d1, d2], "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 1)

    def test_resolved_superseded_concern_marks_topic_accepted(self):
        """Resolving a superseded-decision concern marks its topic as additive."""
        topic = "retro-try-answer-recording"
        # Resolved concern sits at the start of the log — NOT between the
        # most-recent decision pair. This isolates the "accepted topic" rule
        # from the existing "intervening concern" check.
        old_concern = make_event(
            "concern",
            content=f"Superseded decision: topic '{topic}' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            "status",
            content="Accepted as additive",
            metadata={"resolves": [old_concern["id"]]},
        )
        d1 = make_event("decision", topic=topic, content="First")
        d2 = make_event("decision", topic=topic, content="Second")
        d3 = make_event("decision", topic=topic, content="Third")
        events = [old_concern, resolution, d1, d2, d3]
        found = concerns.detect_conflicts(events, "main")
        superseded = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded), 0)

    def test_resolved_superseded_different_topic_does_not_cross_contaminate(self):
        """Accepted topic acceptance is topic-scoped, not global."""
        # Topic A: resolved superseded concern
        accepted_concern = make_event(
            "concern",
            content="Superseded decision: topic 'topic-a' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            "status",
            content="Accepted",
            metadata={"resolves": [accepted_concern["id"]]},
        )
        # Topic B: fresh pair, should still fire
        d1 = make_event("decision", topic="topic-b", content="Use X")
        d2 = make_event("decision", topic="topic-b", content="Use Y")
        events = [accepted_concern, resolution, d1, d2]
        found = concerns.detect_conflicts(events, "main")
        b_concerns = [c for c in found if "topic 'topic-b'" in c["content"]]
        self.assertEqual(len(b_concerns), 1)

    def test_resolved_superseded_still_triggers_other_patterns(self):
        """Accepted-topic skip is pattern-#5-only — other patterns still fire."""
        # Resolved superseded concern for topic 'naming'
        accepted = make_event(
            "concern",
            content="Superseded decision: topic 'naming' has multiple "
            "decisions without an intervening concern.",
        )
        resolution = make_event(
            "status",
            content="Accepted",
            metadata={"resolves": [accepted["id"]]},
        )
        # Convention violation on topic 'naming' — pattern #3 should still fire
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event("decision", topic="naming", content="Use snake_case")
        events = [accepted, resolution, conv, dec]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 1)

    def test_no_duplicate_superseded_decision(self):
        """Should not re-generate concern if one already exists for same conflict."""
        d1 = make_event("decision", topic="db", content="Use Postgres")
        existing_concern = make_event(
            "concern",
            content="Superseded decision: topic 'db' has multiple "
            "decisions without an intervening concern.",
        )
        d2 = make_event("decision", topic="db", content="Use MySQL")
        events = [d1, existing_concern, d2]
        found = concerns.detect_conflicts(events, "main")
        superseded_concerns = [c for c in found if "superseded" in c["content"].lower()]
        self.assertEqual(len(superseded_concerns), 0)

    def test_no_duplicate_assumption_contradicted(self):
        """Should not re-generate concern if one already exists for same conflict."""
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        existing_concern = make_event(
            "concern",
            content="Assumption contradicted: 'API is REST' "
            "contradicted by discovery 'Actually GraphQL'.",
        )
        events = [a, d, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        contradiction_concerns = [
            c for c in found if "contradict" in c["content"].lower()
        ]
        self.assertEqual(len(contradiction_concerns), 0)

    def test_no_duplicate_stale_question(self):
        """No duplicate concern for same stale question."""
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        existing_concern = make_event(
            "concern",
            content="Stale question: blocking question "
            f"(id {q['id']}) has not been answered.",
        )
        events = [q, *filler, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        stale_concerns = [c for c in found if "stale" in c["content"].lower()]
        self.assertEqual(len(stale_concerns), 0)

    def test_resolved_concern_allows_re_detection(self):
        """Resolved concerns should not suppress re-detection."""
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event("decision", topic="naming", content="Use snake_case")
        concern_content = (
            "Convention violation: decision on 'naming' "
            "diverges from established convention."
        )
        old_concern = make_event("concern", content=concern_content)
        # Resolve the old concern
        resolution = make_event(
            "status",
            content="Concern resolved",
            metadata={"resolves": [old_concern["id"]]},
        )
        events = [conv, dec, old_concern, resolution]
        found = concerns.detect_conflicts(events, "main")
        convention_concerns = [c for c in found if "convention" in c["content"].lower()]
        self.assertEqual(len(convention_concerns), 1)


class TestAppendSafeBudget(_HookTestCase):
    """Verify _common.append_safe drops over-budget events silently."""

    def test_append_safe_drops_over_budget(self):
        event = make_event("status", content="x" * 201, working_on=[])
        _common.append_safe(self.smm_dir, event)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_append_safe_writes_within_budget(self):
        event = make_event("status", content="x" * 200, working_on=[])
        _common.append_safe(self.smm_dir, event)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
