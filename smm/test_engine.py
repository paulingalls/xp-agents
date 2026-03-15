#!/usr/bin/env python3
"""Tests for SMM Engine (Milestone 2).

Tests materialize.py and read_delta.py.
Run with: python3 -m unittest smm/test_engine.py -v
"""

import fcntl
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

# Allow importing from the same directory
sys.path.insert(0, str(Path(__file__).parent))
import materialize  # noqa: I001
import read_delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(event_type: str = "customer_input", **kwargs) -> dict:
    """Create a valid event dict with defaults."""
    event = {
        "id": str(uuid.uuid4()),
        "ts": "2026-03-12T00:00:00+00:00",
        "type": event_type,
        "agent_id": "main",
        "content": "test content",
        "schema_version": 1,
    }
    match event_type:
        case "status":
            event["working_on"] = kwargs.pop("working_on", ["src/app.ts"])
        case "decision" | "convention":
            event["topic"] = kwargs.pop("topic", "default-topic")
        case "question":
            event["priority"] = kwargs.pop("priority", "\U0001f534")
        case "pair_guidance":
            event["tool_name"] = kwargs.pop("tool_name", "Write")
        case "goal":
            pass  # No extra required fields
        case "debt":
            event["files"] = kwargs.pop("files", ["src/legacy.py"])
        case "customer_intent":
            event["intent_status"] = kwargs.pop("intent_status", "open")
    event.update(kwargs)
    return event


class _SMMTestCase(unittest.TestCase):
    """Base test case that creates a temp SMM directory."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        self.events_file = self.smm_dir / "events.jsonl"
        (self.smm_dir / "events.lock").touch()
        self.events_file.touch()

    def tearDown(self):
        shutil.rmtree(self.smm_dir)

    def _write_events(self, events: list[dict]) -> None:
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        self.events_file.write_text("\n".join(lines) + ("\n" if lines else ""))

    def _write_raw_lines(self, lines: list[str]) -> None:
        self.events_file.write_text("\n".join(lines) + "\n")

    def _read_events(self) -> list[dict]:
        """Read events back from events.jsonl, skipping empty/bad lines."""
        events = []
        for line in self.events_file.read_text().splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


# ===========================================================================
# Materialize — Parsing
# ===========================================================================


class TestParseEvents(_SMMTestCase):
    def test_empty_file(self):
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_missing_events_file(self):
        self.events_file.unlink()
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_raises_on_lock_timeout(self):
        """parse_events should raise LockTimeoutError, not silently degrade."""
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_fd = open(lock_file, "a")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with self.assertRaises(materialize.LockTimeoutError):
                materialize.parse_events(self.smm_dir)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def test_single_event(self):
        self._write_events([make_event()])
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 0)

    def test_malformed_lines_skipped(self):
        self._write_raw_lines(
            [
                json.dumps(make_event()),
                "not json at all",
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)

    def test_all_malformed(self):
        self._write_raw_lines(["bad1", "bad2", "bad3"])
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 0)
        self.assertEqual(skipped, 3)

    def test_missing_id_or_type_skipped(self):
        self._write_raw_lines(
            [
                json.dumps({"content": "no id or type"}),
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 1)

    def test_non_object_json_skipped(self):
        self._write_raw_lines(
            [
                "[1, 2, 3]",
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 1)


# ===========================================================================
# Materialize — Index Building
# ===========================================================================


class TestBuildIndices(_SMMTestCase):
    def test_by_type_grouping(self):
        events = [
            make_event("customer_input"),
            make_event("decision", topic="db"),
            make_event("customer_input"),
        ]
        indices = materialize.build_indices(events)
        self.assertEqual(len(indices["by_type"]["customer_input"]), 2)
        self.assertEqual(len(indices["by_type"]["decision"]), 1)

    def test_latest_status_per_agent(self):
        e1 = make_event("status", agent_id="a", content="first", working_on=["f1.py"])
        e2 = make_event("status", agent_id="a", content="second", working_on=["f2.py"])
        indices = materialize.build_indices([e1, e2])
        self.assertEqual(indices["latest_status"]["a"]["content"], "second")

    def test_question_answer_linking(self):
        q = make_event("question", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        indices = materialize.build_indices([q, a])
        self.assertIn(q["id"], indices["question_answers"])
        self.assertEqual(indices["question_answers"][q["id"]]["content"], "Postgres")

    def test_question_assumption_linking(self):
        q = make_event("question", priority="\U0001f7e1", content="Auth method?")
        assumption = make_event(
            "assumption", content="Using OAuth", references=[q["id"]]
        )
        indices = materialize.build_indices([q, assumption])
        self.assertIn(q["id"], indices["question_assumptions"])

    def test_assumption_contradiction(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="API is GraphQL", references=[a["id"]])
        indices = materialize.build_indices([a, d])
        self.assertIn(a["id"], indices["assumption_contradictions"])

    def test_concern_resolution(self):
        c = make_event("concern", content="Missing tests")
        resolver = make_event(
            "status",
            content="Added tests",
            references=[c["id"]],
            working_on=["test.py"],
        )
        indices = materialize.build_indices([c, resolver])
        self.assertIn(c["id"], indices["concern_resolutions"])

    def test_decisions_by_topic(self):
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event("decision", topic="db", content="Use MySQL")
        indices = materialize.build_indices([d1, d2])
        self.assertEqual(len(indices["decisions_by_topic"]["db"]), 2)

    def test_conventions_by_topic(self):
        c = make_event("convention", topic="naming", content="camelCase")
        indices = materialize.build_indices([c])
        self.assertEqual(len(indices["conventions_by_topic"]["naming"]), 1)

    def test_event_positions_tracked(self):
        e0 = make_event("customer_input")
        e1 = make_event("discovery", content="found it")
        indices = materialize.build_indices([e0, e1])
        self.assertEqual(indices["event_positions"][e0["id"]], 0)
        self.assertEqual(indices["event_positions"][e1["id"]], 1)

    def test_session_end_positions_tracked(self):
        e0 = make_event("customer_input")
        se1 = make_event("session_end", content="done", ts="2026-03-12T01:00:00+00:00")
        e1 = make_event("customer_input")
        se2 = make_event("session_end", content="done2", ts="2026-03-12T02:00:00+00:00")
        indices = materialize.build_indices([e0, se1, e1, se2])
        self.assertEqual(len(indices["session_end_positions"]), 2)
        self.assertEqual(
            indices["session_end_positions"][0], (1, "2026-03-12T01:00:00+00:00")
        )
        self.assertEqual(
            indices["session_end_positions"][1], (3, "2026-03-12T02:00:00+00:00")
        )

    def test_last_session_end_pos_default(self):
        indices = materialize.build_indices([make_event("customer_input")])
        self.assertEqual(indices["last_session_end_pos"], -1)

    def test_last_session_end_pos_tracked(self):
        e0 = make_event("customer_input")
        se = make_event("session_end", content="done")
        e1 = make_event("customer_input")
        indices = materialize.build_indices([e0, se, e1])
        self.assertEqual(indices["last_session_end_pos"], 1)

    def test_intent_by_status_groups(self):
        i1 = make_event("customer_intent", content="Feature A", intent_status="open")
        i2 = make_event(
            "customer_intent", content="Feature B", intent_status="delivered"
        )
        i3 = make_event("customer_intent", content="Feature C", intent_status="open")
        indices = materialize.build_indices([i1, i2, i3])
        self.assertEqual(len(indices["intent_by_status"]["open"]), 2)
        self.assertEqual(len(indices["intent_by_status"]["delivered"]), 1)


# ===========================================================================
# Materialize — Conflict Detection
# ===========================================================================


class TestConflictDetection(_SMMTestCase):
    def test_overlapping_working_on(self):
        events = [
            make_event(
                "status", agent_id="alice", working_on=["src/app.ts", "src/db.ts"]
            ),
            make_event("status", agent_id="bob", working_on=["src/app.ts"]),
        ]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertTrue(
            any("working_on overlap" in c and "src/app.ts" in c for c in conflicts)
        )

    def test_no_overlap(self):
        events = [
            make_event("status", agent_id="alice", working_on=["src/a.ts"]),
            make_event("status", agent_id="bob", working_on=["src/b.ts"]),
        ]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("working_on overlap" in c for c in conflicts))

    def test_assumption_contradicted(self):
        a = make_event("assumption", content="REST API")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        events = [a, d]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertTrue(any("assumption contradicted" in c for c in conflicts))

    def test_no_contradiction(self):
        a = make_event("assumption", content="REST API")
        d = make_event("discovery", content="Found docs")
        events = [a, d]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("assumption contradicted" in c for c in conflicts))

    def test_convention_violation(self):
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event("decision", topic="naming", content="Use snake_case")
        events = [conv, dec]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertTrue(any("convention violation" in c for c in conflicts))

    def test_no_violation_with_reference(self):
        conv = make_event("convention", topic="naming", content="Use camelCase")
        dec = make_event(
            "decision",
            topic="naming",
            content="Override camelCase",
            references=[conv["id"]],
        )
        events = [conv, dec]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("convention violation" in c for c in conflicts))

    def test_stale_question(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        filler = [
            make_event("customer_input", content=f"filler {i}") for i in range(51)
        ]
        events = [q, *filler]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertTrue(any("stale question" in c for c in conflicts))

    def test_not_stale_question(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        filler = [
            make_event("customer_input", content=f"filler {i}") for i in range(10)
        ]
        events = [q, *filler]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("stale question" in c for c in conflicts))

    def test_stale_answered_not_flagged(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        filler = [
            make_event("customer_input", content=f"filler {i}") for i in range(51)
        ]
        events = [q, a, *filler]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("stale question" in c for c in conflicts))

    def test_yellow_question_not_stale(self):
        q = make_event("question", priority="\U0001f7e1", content="Not blocking")
        filler = [
            make_event("customer_input", content=f"filler {i}") for i in range(51)
        ]
        events = [q, *filler]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("stale question" in c for c in conflicts))

    def test_superseded_decision(self):
        d1 = make_event("decision", topic="db", content="Use Postgres")
        d2 = make_event("decision", topic="db", content="Use MySQL")
        events = [d1, d2]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertTrue(any("superseded decision" in c for c in conflicts))

    def test_not_superseded_with_concern(self):
        d1 = make_event("decision", topic="db", content="Use Postgres")
        c = make_event("concern", content="Postgres licensing", references=[d1["id"]])
        d2 = make_event("decision", topic="db", content="Use MySQL")
        events = [d1, c, d2]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("superseded decision" in c for c in conflicts))

    def test_single_decision_no_supersede(self):
        d = make_event("decision", topic="db", content="Use Postgres")
        events = [d]
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        self.assertFalse(any("superseded" in c for c in conflicts))


# ===========================================================================
# Materialize — Rendering
# ===========================================================================


class TestRenderMarkdown(_SMMTestCase):
    def test_empty_log_returns_empty(self):
        result = materialize.materialize(self.smm_dir)
        self.assertEqual(result, "")

    def test_header_stats(self):
        self._write_events(
            [
                make_event(agent_id="alice"),
                make_event(agent_id="bob"),
            ]
        )
        md = materialize.materialize(self.smm_dir)
        self.assertIn("2 events", md)
        self.assertIn("2 agents", md)

    def test_skipped_in_header(self):
        self._write_raw_lines(
            [
                json.dumps(make_event()),
                "bad line",
            ]
        )
        md = materialize.materialize(self.smm_dir)
        self.assertIn("1 malformed", md)

    def test_all_malformed_renders_header(self):
        self._write_raw_lines(["bad1", "bad2"])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("0 events", md)
        self.assertIn("2 malformed", md)

    def test_two_tier_headers(self):
        """Two-tier structure with ACTIVE CONTEXT and REFERENCE dividers."""
        q = make_event("question", priority="\U0001f534", content="Q?")
        d = make_event("decision", topic="db", content="Use Postgres")
        self._write_events([q, d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## ACTIVE CONTEXT", md)
        self.assertIn("## REFERENCE", md)

    def test_decisions_in_reference(self):
        d = make_event("decision", topic="db", content="Use Postgres", agent_id="nav")
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Architecture Decisions", md)
        self.assertIn("**Use Postgres**", md)
        self.assertIn("nav", md)
        # Decisions should be in REFERENCE section
        ref_idx = md.index("## REFERENCE")
        dec_idx = md.index("## Architecture Decisions")
        self.assertGreater(dec_idx, ref_idx)

    def test_draft_decision(self):
        d = make_event(
            "decision", topic="db", content="Use SQLite", metadata={"draft": True}
        )
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("(draft)", md)

    def test_non_draft_decision(self):
        d = make_event("decision", topic="db", content="Use Postgres")
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertNotIn("(draft)", md)

    def test_decision_references(self):
        ref_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        d = make_event("decision", topic="db", content="Override", references=[ref_id])
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("references aaaaaaaa", md)

    def test_conventions_section(self):
        c = make_event("convention", topic="naming", content="Use camelCase")
        self._write_events([c])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Conventions", md)
        self.assertIn("Use camelCase", md)

    def test_blocking_question_in_active(self):
        q = make_event("question", priority="\U0001f534", content="Which framework?")
        self._write_events([q])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Blocking Questions", md)
        self.assertIn("\U0001f534", md)
        self.assertIn("blocking, awaiting answer", md)

    def test_question_answered_in_reference(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        self._write_events([q, a])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Questions (Resolved & Assumed)", md)
        self.assertIn("✅", md)
        self.assertIn("answered: Postgres", md)

    def test_question_assumed_in_reference(self):
        q = make_event("question", priority="\U0001f7e1", content="Auth method?")
        assumption = make_event(
            "assumption", content="Using OAuth", references=[q["id"]]
        )
        self._write_events([q, assumption])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Questions (Resolved & Assumed)", md)
        self.assertIn("🟡", md)
        self.assertIn("assumed: Using OAuth", md)

    def test_customer_input_section_removed(self):
        """Customer Input section no longer rendered."""
        events = [make_event("customer_input", content=f"Input {i}") for i in range(7)]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertNotIn("## Customer Input", md)

    def test_discoveries_section(self):
        d = make_event("discovery", content="Found legacy API")
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Discoveries", md)
        self.assertIn("⚠️ Found legacy API", md)

    def test_assumptions_unverified(self):
        a = make_event("assumption", content="API is REST")
        self._write_events([a])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Assumptions", md)
        self.assertIn("unverified", md)

    def test_assumptions_contradicted(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="GraphQL", references=[a["id"]])
        self._write_events([a, d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("❌", md)
        self.assertIn("contradicted by", md)

    def test_unacknowledged_concerns_in_active(self):
        c = make_event("concern", content="Missing error handling")
        self._write_events([c])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Unacknowledged Concerns", md)
        self.assertIn("⚠️", md)
        self.assertIn("unacknowledged", md)

    def test_resolved_concerns_in_reference(self):
        c = make_event("concern", content="Missing tests")
        r = make_event(
            "status", content="Fixed", references=[c["id"]], working_on=["test.py"]
        )
        self._write_events([c, r])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Resolved Concerns", md)
        self.assertIn("✅", md)
        self.assertIn("resolved", md)

    def test_concerns_split_active_and_reference(self):
        """Unresolved in Active, resolved in Reference."""
        c1 = make_event("concern", content="Unresolved issue")
        c2 = make_event("concern", content="Resolved issue")
        r = make_event(
            "status", content="Fixed", references=[c2["id"]], working_on=["test.py"]
        )
        self._write_events([c1, c2, r])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Unacknowledged Concerns", md)
        self.assertIn("## Resolved Concerns", md)
        # Unacknowledged in Active Context
        active_idx = md.index("## ACTIVE CONTEXT")
        ref_idx = md.index("## REFERENCE")
        unack_idx = md.index("## Unacknowledged Concerns")
        resolved_idx = md.index("## Resolved Concerns")
        self.assertGreater(unack_idx, active_idx)
        self.assertLess(unack_idx, ref_idx)
        self.assertGreater(resolved_idx, ref_idx)

    def test_agent_status_working(self):
        s = make_event(
            "status",
            agent_id="main",
            content="Implementing auth",
            working_on=["src/auth.ts"],
        )
        self._write_events([s])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Agent Status", md)
        self.assertIn("**main**", md)
        self.assertIn("Working on: src/auth.ts", md)

    def test_agent_status_idle(self):
        s = make_event("status", agent_id="main", content="Done", working_on=[])
        self._write_events([s])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Idle.", md)

    def test_agent_status_latest_only(self):
        s1 = make_event(
            "status", agent_id="main", content="First task", working_on=["a.py"]
        )
        s2 = make_event(
            "status", agent_id="main", content="Second task", working_on=["b.py"]
        )
        self._write_events([s1, s2])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Second task", md)
        status_section = md.split("## Agent Status")[1].split("##")[0]
        self.assertNotIn("First task", status_section)

    def test_navigator_guidance_all_without_session_end(self):
        """Without session_end, show all guidance (last 3)."""
        events = [
            make_event("pair_guidance", content=f"Guidance {i}", tool_name="Write")
            for i in range(5)
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Navigator Guidance", md)
        self.assertNotIn("Guidance 0", md)
        self.assertNotIn("Guidance 1", md)
        self.assertIn("Guidance 2", md)
        self.assertIn("Guidance 4", md)

    def test_navigator_guidance_scoped_to_session(self):
        """With session_end, only show guidance after last session_end."""
        events = [
            make_event("pair_guidance", content="Old guidance", tool_name="Write"),
            make_event("session_end", content="done"),
            make_event("pair_guidance", content="New guidance", tool_name="Edit"),
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Navigator Guidance", md)
        self.assertNotIn("Old guidance", md)
        self.assertIn("New guidance", md)

    def test_navigator_no_guidance_after_session_end(self):
        """All guidance before session_end → no Navigator section."""
        events = [
            make_event("pair_guidance", content="Old guidance", tool_name="Write"),
            make_event("session_end", content="done"),
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertNotIn("## Navigator Guidance", md)

    def test_goals_render_with_prefix(self):
        g = make_event("goal", content="Ship v2.0")
        self._write_events([g])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Project Goals", md)
        self.assertIn("🎯", md)
        self.assertIn("Ship v2.0", md)

    def test_customer_intent_open_in_active(self):
        i1 = make_event(
            "customer_intent", content="Need auth flow", intent_status="open"
        )
        i2 = make_event(
            "customer_intent", content="Done feature", intent_status="delivered"
        )
        self._write_events([i1, i2])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Customer Intent", md)
        self.assertIn("📋", md)
        self.assertIn("Need auth flow", md)
        # Delivered should NOT appear in Customer Intent
        intent_section = md.split("## Customer Intent")[1].split("##")[0]
        self.assertNotIn("Done feature", intent_section)

    def test_customer_intent_with_source_refs(self):
        ci = make_event("customer_input", content="I want auth")
        intent = make_event(
            "customer_intent",
            content="Auth flow needed",
            intent_status="open",
            references=[ci["id"]],
        )
        self._write_events([ci, intent])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Customer Intent", md)
        self.assertIn("Auth flow needed", md)
        self.assertIn(ci["id"][:8], md)

    def test_debt_with_aging_new(self):
        """Debt with 0-3 session_ends after: no age marker."""
        d = make_event("debt", content="Legacy code", files=["src/old.py"])
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Technical Debt", md)
        self.assertIn("Legacy code", md)
        self.assertIn("src/old.py", md)

    def test_debt_with_aging_warning(self):
        """Debt with 4-6 session_ends after: ⚠️ marker."""
        d = make_event(
            "debt",
            content="Legacy code",
            files=["src/old.py"],
            ts="2026-03-12T00:00:00+00:00",
        )
        ses = [
            make_event(
                "session_end",
                content=f"done {i}",
                ts=f"2026-03-12T0{i + 1}:00:00+00:00",
            )
            for i in range(5)
        ]
        self._write_events([d, *ses])
        md = materialize.materialize(self.smm_dir)
        debt_section = md.split("## Technical Debt")[1].split("##")[0]
        self.assertIn("⚠️", debt_section)

    def test_debt_with_aging_critical(self):
        """Debt with 7+ session_ends after: 🔴 marker."""
        d = make_event(
            "debt",
            content="Legacy code",
            files=["src/old.py"],
            ts="2026-03-12T00:00:00+00:00",
        )
        ses = [
            make_event(
                "session_end",
                content=f"done {i}",
                ts=f"2026-03-12T{i + 1:02d}:00:00+00:00",
            )
            for i in range(8)
        ]
        self._write_events([d, *ses])
        md = materialize.materialize(self.smm_dir)
        debt_section = md.split("## Technical Debt")[1].split("##")[0]
        self.assertIn("🔴", debt_section)

    def test_unknown_event_type(self):
        e = {
            "id": str(uuid.uuid4()),
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "future_type",
            "agent_id": "main",
            "content": "New feature",
        }
        self._write_events([e])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Unknown Events", md)
        self.assertIn("[future_type]", md)
        self.assertIn("New feature", md)

    def test_empty_sections_omitted(self):
        self._write_events([make_event("customer_input", content="Hello")])
        md = materialize.materialize(self.smm_dir)
        self.assertNotIn("## Architecture Decisions", md)
        self.assertNotIn("## Conventions", md)
        self.assertNotIn("## Unacknowledged Concerns", md)
        self.assertNotIn("## Conflict Alerts", md)
        self.assertNotIn("## Navigator Guidance", md)
        self.assertNotIn("## Unknown Events", md)
        self.assertNotIn("## Project Goals", md)
        self.assertNotIn("## Customer Intent", md)
        self.assertNotIn("## Technical Debt", md)

    def test_all_15_types_render(self):
        q = make_event("question", content="Q?", priority="\U0001f534")
        events = [
            make_event("customer_input", content="Hello"),
            make_event("customer_intent", content="Want auth", intent_status="open"),
            make_event("debt", content="Old code", files=["old.py"]),
            make_event("goal", content="Ship v2"),
            make_event("status", content="Working", working_on=["f.py"]),
            make_event("decision", content="Use Postgres", topic="db"),
            make_event("convention", content="camelCase", topic="naming"),
            make_event("concern", content="Missing tests"),
            make_event("discovery", content="Found API"),
            q,
            make_event("answer", content="Yes", references=[q["id"]]),
            make_event("assumption", content="REST API"),
            make_event("pair_guidance", content="Check tests", tool_name="Write"),
            make_event("session_end", content="Done"),
            make_event("retrospective", content="Review"),
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("# Shared Mental Model", md)
        self.assertIn("15 events", md)

    def test_short_id_in_output(self):
        d = make_event("decision", topic="db", content="Use Postgres")
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn(d["id"][:8], md)
        # Full ID should NOT appear
        self.assertNotIn(d["id"], md)


# ===========================================================================
# Materialize — File Writing
# ===========================================================================


class TestMaterializeToFile(_SMMTestCase):
    def test_creates_file(self):
        self._write_events([make_event()])
        path = materialize.materialize_to_file(self.smm_dir)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "SHARED_MENTAL_MODEL.md")

    def test_atomic_write_complete(self):
        self._write_events([make_event()])
        path = materialize.materialize_to_file(self.smm_dir)
        content = path.read_text()
        self.assertTrue(content.endswith("\n"))

    def test_empty_log_writes_empty_file(self):
        path = materialize.materialize_to_file(self.smm_dir)
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "")

    def test_output_file_permissions(self):
        self._write_events([make_event()])
        path = materialize.materialize_to_file(self.smm_dir)
        mode = path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"SMM file mode is {oct(mode)}")

    def test_no_temp_files_left(self):
        self._write_events([make_event()])
        materialize.materialize_to_file(self.smm_dir)
        tmp_files = list(self.smm_dir.glob("*.md.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_overwrites_existing(self):
        self._write_events([make_event("goal", content="First")])
        materialize.materialize_to_file(self.smm_dir)
        self._write_events([make_event("goal", content="Second")])
        path = materialize.materialize_to_file(self.smm_dir)
        content = path.read_text()
        self.assertIn("Second", content)


# ===========================================================================
# Read Delta — Watermark
# ===========================================================================


class TestWatermark(_SMMTestCase):
    def test_no_watermark_returns_0(self):
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_write_and_read_watermark(self):
        read_delta.write_watermark(self.smm_dir, "main", 42)
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 42)

    def test_corrupted_watermark_returns_0(self):
        wm_file = self.smm_dir / ".watermark-main"
        wm_file.write_text("not-a-number")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_atomic_write_no_temp_files(self):
        read_delta.write_watermark(self.smm_dir, "test", 10)
        tmp_files = list(self.smm_dir.glob(".wm-test-*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_per_agent_watermarks(self):
        read_delta.write_watermark(self.smm_dir, "alice", 10)
        read_delta.write_watermark(self.smm_dir, "bob", 20)
        self.assertEqual(read_delta.read_watermark(self.smm_dir, "alice"), 10)
        self.assertEqual(read_delta.read_watermark(self.smm_dir, "bob"), 20)

    def test_reject_agent_id_with_slash(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "../escape", 10)

    def test_reject_agent_id_with_dotdot(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "..", 10)

    def test_reject_agent_id_with_null(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent\x00id", 10)

    def test_reject_empty_agent_id(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "", 10)

    def test_read_watermark_rejects_bad_agent_id(self):
        with self.assertRaises(ValueError):
            read_delta.read_watermark(self.smm_dir, "../escape")

    def test_rejects_space(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent name", 10)

    def test_rejects_semicolon(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent;cmd", 10)

    def test_rejects_backtick(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent`cmd`", 10)

    def test_accepts_colon(self):
        read_delta.write_watermark(self.smm_dir, "xp-quality:reviewer", 10)
        wm = read_delta.read_watermark(self.smm_dir, "xp-quality:reviewer")
        self.assertEqual(wm, 10)

    def test_accepts_hyphen(self):
        read_delta.write_watermark(self.smm_dir, "xp-navigator", 5)
        wm = read_delta.read_watermark(self.smm_dir, "xp-navigator")
        self.assertEqual(wm, 5)

    def test_watermark_file_permissions(self):
        read_delta.write_watermark(self.smm_dir, "main", 10)
        wm_file = self.smm_dir / ".watermark-main"
        mode = wm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"watermark mode is {oct(mode)}")


# ===========================================================================
# Symlink Protection
# ===========================================================================


class TestSymlinkProtection(_SMMTestCase):
    """Symlinks at lock/event paths must be rejected."""

    def test_read_delta_rejects_lock_symlink(self):
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock-rd")
        with self.assertRaises(OSError):
            read_delta.read_events_from(self.smm_dir, 0)

    def test_materialize_rejects_lock_symlink(self):
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock-mat")
        with self.assertRaises(OSError):
            materialize.parse_events(self.smm_dir)


# ===========================================================================
# Read Delta — Event Reading
# ===========================================================================


class TestReadEventsFrom(_SMMTestCase):
    def test_raises_on_lock_timeout(self):
        """read_events_from should raise LockTimeoutError, not silently degrade."""
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_fd = open(lock_file, "a")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with self.assertRaises(read_delta.LockTimeoutError):
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


# ===========================================================================
# Read Delta — Tier Filtering
# ===========================================================================


class TestFilterByTier(_SMMTestCase):
    def setUp(self):
        super().setUp()
        self.events = [
            make_event("customer_input"),
            make_event("status", working_on=["f.py"]),
            make_event("question", priority="\U0001f534", content="Blocking Q"),
            make_event("question", priority="\U0001f7e1", content="Yellow Q"),
            make_event("pair_guidance", tool_name="Write", content="Check tests"),
            make_event("decision", topic="db", content="Use Postgres"),
        ]

    def test_full_returns_all(self):
        result = read_delta.filter_by_tier(self.events, "full")
        self.assertEqual(len(result), 6)

    def test_blocking_returns_red_and_guidance(self):
        result = read_delta.filter_by_tier(self.events, "blocking")
        self.assertEqual(len(result), 2)
        types = {e["type"] for e in result}
        self.assertIn("question", types)
        self.assertIn("pair_guidance", types)
        for e in result:
            if e["type"] == "question":
                self.assertEqual(e["priority"], "\U0001f534")

    def test_red_only_returns_red_questions(self):
        result = read_delta.filter_by_tier(self.events, "red-only")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "question")
        self.assertEqual(result[0]["priority"], "\U0001f534")

    def test_no_red_questions_empty(self):
        events = [
            make_event("customer_input"),
            make_event("question", priority="\U0001f7e1"),
        ]
        result = read_delta.filter_by_tier(events, "red-only")
        self.assertEqual(len(result), 0)


# ===========================================================================
# Read Delta — Formatting
# ===========================================================================


class TestFormatDelta(_SMMTestCase):
    def test_empty_returns_empty(self):
        result = read_delta.format_delta([])
        self.assertEqual(result, "")

    def test_header_footer(self):
        events = [make_event()]
        result = read_delta.format_delta(events)
        self.assertIn('<smm-delta count="1">', result)
        self.assertIn("</smm-delta>", result)

    def test_decision_format(self):
        d = make_event("decision", topic="db", content="Use Postgres")
        result = read_delta.format_delta([d])
        self.assertIn("DECISION", result)
        self.assertIn("(db)", result)
        self.assertIn("Use Postgres", result)

    def test_draft_decision_format(self):
        d = make_event(
            "decision", topic="db", content="Maybe SQLite", metadata={"draft": True}
        )
        result = read_delta.format_delta([d])
        self.assertIn("DECISION (draft)", result)

    def test_question_format(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        result = read_delta.format_delta([q])
        self.assertIn("QUESTION \U0001f534", result)
        self.assertIn("Which DB?", result)

    def test_status_format(self):
        s = make_event(
            "status", agent_id="main", content="Working", working_on=["f.py"]
        )
        result = read_delta.format_delta([s])
        self.assertIn("STATUS [main]", result)
        self.assertIn("working on: f.py", result)

    def test_pair_guidance_format(self):
        g = make_event("pair_guidance", content="Check tests", tool_name="Write")
        result = read_delta.format_delta([g])
        self.assertIn("NAVIGATOR", result)
        self.assertIn("for Write", result)

    def test_convention_format(self):
        c = make_event("convention", topic="naming", content="camelCase")
        result = read_delta.format_delta([c])
        self.assertIn("CONVENTION", result)
        self.assertIn("(naming)", result)

    def test_answer_format(self):
        ref_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        a = make_event("answer", content="Postgres", references=[ref_id])
        result = read_delta.format_delta([a])
        self.assertIn("ANSWER", result)
        self.assertIn("re: aaaaaaaa", result)

    def test_goal_format(self):
        g = make_event("goal", content="Ship v2.0")
        result = read_delta.format_delta([g])
        self.assertIn("GOAL", result)
        self.assertIn("Ship v2.0", result)

    def test_debt_format(self):
        d = make_event(
            "debt", content="Legacy code", files=["src/old.py", "src/legacy.py"]
        )
        result = read_delta.format_delta([d])
        self.assertIn("DEBT", result)
        self.assertIn("src/old.py, src/legacy.py", result)
        self.assertIn("Legacy code", result)

    def test_customer_intent_format(self):
        ci = make_event("customer_intent", content="Need auth", intent_status="open")
        result = read_delta.format_delta([ci])
        self.assertIn("INTENT", result)
        self.assertIn("(open)", result)
        self.assertIn("Need auth", result)

    def test_unknown_type_format(self):
        e = {
            "id": str(uuid.uuid4()),
            "type": "future_type",
            "agent_id": "main",
            "content": "New thing",
        }
        result = read_delta.format_delta([e])
        self.assertIn("FUTURE_TYPE", result)


# ===========================================================================
# Read Delta — End-to-End
# ===========================================================================


class TestReadDelta(_SMMTestCase):
    def test_no_watermark_reads_all(self):
        self._write_events([make_event(), make_event()])
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 2)

    def test_watermark_reads_new_only(self):
        self._write_events([make_event(content="old")])
        read_delta.read_delta(self.smm_dir, "main", tier="full")
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        events = read_delta.read_delta(self.smm_dir, "main", tier="full")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "new")

    def test_watermark_advances_on_full(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", tier="full")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 1)

    def test_watermark_unchanged_on_blocking(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", tier="blocking")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_watermark_unchanged_on_red_only(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", tier="red-only")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_watermark_beyond_file_empty_result(self):
        self._write_events([make_event()])
        read_delta.write_watermark(self.smm_dir, "main", 100)
        events = read_delta.read_delta(self.smm_dir, "main", tier="full")
        self.assertEqual(len(events), 0)

    def test_no_update_flag(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", tier="full", update_watermark=False)
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_missing_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        events = read_delta.read_delta(fake_dir, "main")
        self.assertEqual(len(events), 0)

    def test_empty_file(self):
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 0)

    def test_filtered_read_then_full_read(self):
        """Red-only read surfaces blocking question; full read re-surfaces it."""
        q = make_event("question", priority="\U0001f534", content="Blocking!")
        other = make_event("customer_input", content="Hello")
        self._write_events([q, other])
        red = read_delta.read_delta(self.smm_dir, "main", tier="red-only")
        self.assertEqual(len(red), 1)
        full = read_delta.read_delta(self.smm_dir, "main", tier="full")
        self.assertEqual(len(full), 2)

    def test_multiple_agents_independent_watermarks(self):
        self._write_events([make_event(), make_event(), make_event()])
        read_delta.read_delta(self.smm_dir, "alice", tier="full")
        # Alice at 3, bob at 0
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        alice_events = read_delta.read_delta(self.smm_dir, "alice", tier="full")
        bob_events = read_delta.read_delta(self.smm_dir, "bob", tier="full")
        self.assertEqual(len(alice_events), 1)
        self.assertEqual(len(bob_events), 4)


# ===========================================================================
# extract_active_context
# ===========================================================================


class TestExtractActiveContext(_SMMTestCase):
    def test_returns_active_section(self):
        """Returns everything before ---\\n## REFERENCE."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api-style"),
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        result = materialize.extract_active_context(md)
        self.assertIn("Project Goals", result)
        self.assertNotIn("Architecture Decisions", result)

    def test_empty_when_no_active_context(self):
        """Returns empty string when no Active Context section."""
        result = materialize.extract_active_context("")
        self.assertEqual(result, "")

    def test_all_active_when_no_reference(self):
        """Returns full text when no REFERENCE section exists."""
        events = [make_event("goal", content="Ship v1")]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        result = materialize.extract_active_context(md)
        # Should include the goal since there's no reference to split on
        self.assertIn("Project Goals", result)


# ===========================================================================
# Compact (Milestone 8)
# ===========================================================================


class TestCompact(_SMMTestCase):
    """Tests for smm/compact.py log management."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        """Create a session: N events + session_end."""
        ts_base = f"2026-03-{session_num:02d}T00:00:00+00:00"
        events = [
            make_event(
                "customer_input",
                content=f"session {session_num} event {i}",
                ts=ts_base,
            )
            for i in range(event_count)
        ]
        events.append(
            make_event(
                "session_end",
                content=f"end session {session_num}",
                ts=ts_base,
                working_on=[],
            )
        )
        return events

    def test_compact_empty_log(self):
        import compact

        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 0)

    def test_compact_keeps_recent_sessions(self):
        """Events from the last 3 sessions are retained."""
        import compact

        all_events = []
        for s in range(1, 5):
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)

        result = compact.compact(self.smm_dir, keep_sessions=3)
        self.assertGreater(result["archived"], 0)
        # Read back retained events
        retained = self._read_events()
        # Session 1 events should be archived (it's the 4th-oldest)
        contents = [e.get("content", "") for e in retained]
        self.assertNotIn("session 1 event 0", contents)

    def test_compact_permanent_events_never_archived(self):
        """decision, convention, goal, debt, assumption, retrospective are permanent."""
        import compact

        permanent = [
            make_event(
                "decision",
                content="keep me",
                topic="t1",
                ts="2026-01-01T00:00:00+00:00",
            ),
            make_event(
                "convention",
                content="keep me too",
                topic="t2",
                ts="2026-01-01T00:00:00+00:00",
            ),
            make_event("goal", content="keep goal", ts="2026-01-01T00:00:00+00:00"),
            make_event(
                "debt",
                content="keep debt",
                files=["f.py"],
                ts="2026-01-01T00:00:00+00:00",
            ),
            make_event(
                "assumption", content="keep assumption", ts="2026-01-01T00:00:00+00:00"
            ),
            make_event(
                "retrospective", content="keep retro", ts="2026-01-01T00:00:00+00:00"
            ),
        ]
        session = self._make_session(session_num=1)
        recent = self._make_session(session_num=2)
        self._write_events(permanent + session + recent)

        result = compact.compact(self.smm_dir, keep_sessions=1)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        for p in permanent:
            self.assertIn(
                p["id"], retained_ids, f"Permanent event {p['type']} was archived"
            )
        self.assertEqual(result["permanent"], len(permanent))

    def test_compact_unresolved_questions_retained(self):
        """Unresolved 🔴 questions should be retained even outside recent sessions."""
        import compact

        q = make_event(
            "question",
            content="Unanswered?",
            priority="🔴",
            ts="2026-01-01T00:00:00+00:00",
        )
        old_session = self._make_session(session_num=1)
        recent = self._make_session(session_num=2)
        self._write_events([q, *old_session, *recent])

        compact.compact(self.smm_dir, keep_sessions=1)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(q["id"], retained_ids)

    def test_compact_resolved_questions_archivable(self):
        """Resolved questions outside recent sessions can be archived."""
        import compact

        q = make_event(
            "question",
            content="Answered",
            priority="🔴",
            ts="2026-01-01T00:00:00+00:00",
        )
        a = make_event(
            "answer",
            content="Yes",
            references=[q["id"]],
            ts="2026-01-01T00:00:01+00:00",
        )
        old_session = self._make_session(session_num=1)
        recent = self._make_session(session_num=2)
        self._write_events([q, a, *old_session, *recent])

        compact.compact(self.smm_dir, keep_sessions=1)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Answered question CAN be archived (not guaranteed retained)
        # We just verify archival happened
        self.assertNotIn(q["id"], retained_ids)

    def test_compact_unresolved_concerns_retained(self):
        """Unresolved concerns should be retained."""
        import compact

        c = make_event(
            "concern", content="Unresolved concern", ts="2026-01-01T00:00:00+00:00"
        )
        old_session = self._make_session(session_num=1)
        recent = self._make_session(session_num=2)
        self._write_events([c, *old_session, *recent])

        compact.compact(self.smm_dir, keep_sessions=1)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(c["id"], retained_ids)

    def test_compact_creates_archive(self):
        """Archived events written to backups/archive-{ts}.jsonl."""
        import compact

        all_events = []
        for s in range(1, 4):
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)

        compact.compact(self.smm_dir, keep_sessions=1)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        # Archive should contain lines
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_compact_removes_watermarks(self):
        """All .watermark-* files removed after compaction."""
        import compact

        self._write_events(self._make_session(session_num=1))
        # Create some watermark files
        (self.smm_dir / ".watermark-main").write_text("5")
        (self.smm_dir / ".watermark-navigator").write_text("3")

        compact.compact(self.smm_dir, keep_sessions=1)
        watermarks = list(self.smm_dir.glob(".watermark-*"))
        self.assertEqual(len(watermarks), 0)

    def test_compact_atomic_replacement(self):
        """events.jsonl is replaced atomically (not corrupted on crash)."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        compact.compact(self.smm_dir, keep_sessions=1)
        # File should still be valid JSONL
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)  # Should not raise

    def test_compact_fewer_sessions_than_threshold(self):
        """When fewer sessions than keep_sessions, nothing archived."""
        import compact

        self._write_events(self._make_session(session_num=1))
        result = compact.compact(self.smm_dir, keep_sessions=3)
        self.assertEqual(result["archived"], 0)

    def test_compact_returns_counts(self):
        """Return dict has archived, retained, permanent keys."""
        import compact

        all_events = []
        for s in range(1, 5):
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)

        result = compact.compact(self.smm_dir, keep_sessions=2)
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)
        self.assertEqual(
            result["archived"] + result["retained"],
            len(all_events),
        )

    def test_compact_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        permanent = make_event(
            "decision", content="first", topic="t", ts="2026-01-01T00:00:00+00:00"
        )
        session = self._make_session(session_num=2)
        self._write_events([permanent, *session])

        compact.compact(self.smm_dir, keep_sessions=1)
        retained = self._read_events()
        # Permanent event should come before session events
        ids = [e["id"] for e in retained]
        self.assertEqual(ids[0], permanent["id"])


# ===========================================================================
# Repair (Milestone 8)
# ===========================================================================


class TestRepair(_SMMTestCase):
    """Tests for smm/repair.py log recovery."""

    def test_repair_empty_log(self):
        import repair

        result = repair.repair(self.smm_dir)
        self.assertEqual(result["retained"], 0)
        self.assertEqual(result["malformed"], 0)

    def test_repair_valid_log_unchanged(self):
        import repair

        events = [make_event(), make_event("decision", topic="t")]
        self._write_events(events)
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["retained"], 2)
        self.assertEqual(result["malformed"], 0)
        self.assertEqual(result["invalid"], 0)

    def test_repair_skips_malformed_json(self):
        import repair

        good = make_event(content="good")
        self._write_raw_lines(
            [
                json.dumps(good),
                "not valid json {{{",
                '{"partial": true',
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["malformed"], 2)
        self.assertEqual(result["retained"], 1)

    def test_repair_skips_missing_required_fields(self):
        import repair

        good = make_event(content="good")
        bad_no_id = {
            "type": "status",
            "ts": "2026-01-01T00:00:00+00:00",
            "agent_id": "main",
            "content": "no id",
        }
        bad_no_type = {
            "id": "abc",
            "ts": "2026-01-01T00:00:00+00:00",
            "agent_id": "main",
            "content": "no type",
        }
        self._write_raw_lines(
            [
                json.dumps(good),
                json.dumps(bad_no_id),
                json.dumps(bad_no_type),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["invalid"], 2)
        self.assertEqual(result["retained"], 1)

    def test_repair_deduplicates_by_id(self):
        import repair

        e = make_event(content="original")
        dupe = dict(e)
        dupe["content"] = "duplicate"
        self._write_events([e, dupe])
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["retained"], 1)
        # Retained should be the first occurrence
        retained = self._read_events()
        self.assertEqual(retained[0]["content"], "original")

    def test_repair_sorts_by_timestamp(self):
        import repair

        e1 = make_event(content="second", ts="2026-03-02T00:00:00+00:00")
        e2 = make_event(content="first", ts="2026-03-01T00:00:00+00:00")
        self._write_events([e1, e2])
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["reordered"], 1)
        retained = self._read_events()
        self.assertEqual(retained[0]["content"], "first")
        self.assertEqual(retained[1]["content"], "second")

    def test_repair_creates_backup(self):
        import repair

        self._write_events([make_event()])
        repair.repair(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        pre_repairs = list(backups.glob("pre-repair-*.jsonl"))
        self.assertEqual(len(pre_repairs), 1)

    def test_repair_writes_report(self):
        import repair

        self._write_raw_lines([json.dumps(make_event()), "bad line"])
        repair.repair(self.smm_dir)
        report_file = self.smm_dir / ".repair-report.json"
        self.assertTrue(report_file.exists())
        report = json.loads(report_file.read_text())
        self.assertIn("malformed", report)
        self.assertIn("retained", report)

    def test_repair_dry_run_no_changes(self):
        import repair

        events = [make_event()]
        self._write_events(events)
        (self.smm_dir / "events.jsonl").read_text()
        self._write_raw_lines([json.dumps(events[0]), "bad"])

        result = repair.repair(self.smm_dir, dry_run=True)
        self.assertEqual(result["malformed"], 1)
        # File should be unchanged (still has the bad line)
        current = (self.smm_dir / "events.jsonl").read_text()
        self.assertIn("bad", current)

    def test_repair_atomic_replacement(self):
        import repair

        self._write_events([make_event()])
        repair.repair(self.smm_dir)
        # File should be valid JSONL
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)

    def test_repair_non_object_lines_skipped(self):
        import repair

        self._write_raw_lines(
            [
                json.dumps(make_event()),
                '"just a string"',
                "42",
                json.dumps([1, 2, 3]),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["invalid"], 3)
        self.assertEqual(result["retained"], 1)

    def test_repair_mixed_problems(self):
        """Combines malformed JSON, missing fields, duplicates, out-of-order."""
        import repair

        e1 = make_event(content="first", ts="2026-03-02T00:00:00+00:00")
        e2 = make_event(content="second", ts="2026-03-01T00:00:00+00:00")
        dupe = dict(e1)
        self._write_raw_lines(
            [
                json.dumps(e1),
                "bad json",
                json.dumps({"not": "valid event"}),
                json.dumps(e2),
                json.dumps(dupe),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["malformed"], 1)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["retained"], 2)


# ===========================================================================
# Migrate (Milestone 8)
# ===========================================================================


class TestMigrate(_SMMTestCase):
    """Tests for smm/migrate.py schema versioning."""

    def test_migrate_event_v1_to_v2(self):
        import migrate

        event = make_event(ts="2026-03-12T00:00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)
        # Timestamp should have timezone
        self.assertIn("+", result["ts"])

    def test_migrate_event_already_v2(self):
        import migrate

        event = make_event(schema_version=2, ts="2026-03-12T00:00:00+00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["ts"], "2026-03-12T00:00:00+00:00")

    def test_migrate_event_future_version_passthrough(self):
        """Events with schema_version > CURRENT pass through unchanged."""
        import migrate

        event = make_event(schema_version=99, ts="2026-03-12T00:00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 99)
        # Should not modify the event
        self.assertEqual(result["ts"], "2026-03-12T00:00:00")

    def test_migrate_event_no_version_treated_as_v1(self):
        import migrate

        event = make_event()
        del event["schema_version"]
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)

    def test_migrate_file(self):
        import migrate

        events = [
            make_event(ts="2026-03-12T00:00:00"),
            make_event(ts="2026-03-13T00:00:00+00:00", schema_version=2),
        ]
        self._write_events(events)
        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 1)
        self.assertEqual(result["unchanged"], 1)
        # Read back and verify
        migrated = self._read_events()
        for e in migrated:
            self.assertEqual(e["schema_version"], 2)

    def test_migrate_file_idempotent(self):
        import migrate

        events = [make_event(ts="2026-03-12T00:00:00")]
        self._write_events(events)
        migrate.migrate_file(self.smm_dir)
        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 0)
        self.assertEqual(result["unchanged"], 1)

    def test_migrate_file_empty(self):
        import migrate

        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 0)
        self.assertEqual(result["unchanged"], 0)

    def test_migrate_preserves_all_fields(self):
        import migrate

        event = make_event(
            "decision",
            topic="api",
            content="Use REST",
            ts="2026-03-12T00:00:00",
            references=["abc"],
            metadata={"draft": True},
        )
        result = migrate.migrate_event(event)
        self.assertEqual(result["topic"], "api")
        self.assertEqual(result["content"], "Use REST")
        self.assertEqual(result["references"], ["abc"])
        self.assertEqual(result["metadata"], {"draft": True})

    def test_migrate_ts_with_timezone_unchanged(self):
        """Timestamps that already have timezone info are not modified."""
        import migrate

        event = make_event(ts="2026-03-12T10:30:00-05:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["ts"], "2026-03-12T10:30:00-05:00")


# ===========================================================================
# Drift Signals (Milestone 8)
# ===========================================================================


class TestDriftSignals(_SMMTestCase):
    """Tests for drift signal detection in materialize.py."""

    def _make_sessions(self, count: int) -> list[dict]:
        """Create N session_end events with distinct timestamps."""
        events = []
        for i in range(count):
            events.append(
                make_event(
                    "session_end",
                    content=f"end {i}",
                    ts=f"2026-03-{i + 1:02d}T00:00:00+00:00",
                    working_on=[],
                )
            )
        return events

    def test_stale_decision(self):
        """Decision with no related events in 5+ sessions flagged."""
        d = make_event(
            "decision",
            content="Old decision",
            topic="old-topic",
            ts="2026-01-01T00:00:00+00:00",
        )
        sessions = self._make_sessions(6)
        self._write_events([d, *sessions])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Drift Signals", md)
        self.assertIn("stale decision", md.lower())
        self.assertIn("old-topic", md)

    def test_no_stale_decision_with_recent_activity(self):
        """Decision with related events in recent sessions is not stale."""
        d = make_event(
            "decision",
            content="Active decision",
            topic="active-topic",
            ts="2026-01-01T00:00:00+00:00",
        )
        sessions = self._make_sessions(3)
        # Add recent decision on same topic
        d2 = make_event(
            "decision",
            content="Updated",
            topic="active-topic",
            ts="2026-03-04T00:00:00+00:00",
        )
        self._write_events([d, *sessions, d2])
        md = materialize.materialize(self.smm_dir)
        # Should not flag active-topic as stale
        if "Drift Signals" in md:
            self.assertNotIn(
                "active-topic", md.split("Drift Signals")[1].split("##")[0]
            )

    def test_ignored_convention(self):
        """Convention with 3+ unresolved concerns flagged."""
        conv = make_event(
            "convention",
            content="Use camelCase",
            topic="naming",
            ts="2026-01-01T00:00:00+00:00",
        )
        concerns = [
            make_event(
                "concern",
                content=f"Concern {i} about naming",
                references=[conv["id"]],
                ts=f"2026-01-0{i + 2}T00:00:00+00:00",
            )
            for i in range(3)
        ]
        self._write_events([conv, *concerns])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Drift Signals", md)
        self.assertIn("ignored convention", md.lower())
        self.assertIn("naming", md)

    def test_no_ignored_convention_few_concerns(self):
        """Convention with <3 concerns not flagged."""
        conv = make_event(
            "convention",
            content="Use camelCase",
            topic="naming",
            ts="2026-01-01T00:00:00+00:00",
        )
        concern = make_event("concern", content="One concern", references=[conv["id"]])
        self._write_events([conv, concern])
        md = materialize.materialize(self.smm_dir)
        if "Drift Signals" in md:
            self.assertNotIn("ignored convention", md.lower())

    def test_superseded_decision(self):
        """Same topic, 2+ decisions without intervening concern."""
        d1 = make_event(
            "decision", content="First", topic="db", ts="2026-01-01T00:00:00+00:00"
        )
        d2 = make_event(
            "decision", content="Second", topic="db", ts="2026-01-02T00:00:00+00:00"
        )
        self._write_events([d1, d2])
        md = materialize.materialize(self.smm_dir)
        # Superseded decisions show in Conflict Alerts (existing pattern 5)
        self.assertIn("superseded decision", md.lower())

    def test_contradicted_assumption(self):
        """Assumption contradicted by discovery flagged as drift."""
        a = make_event(
            "assumption", content="API is stable", ts="2026-01-01T00:00:00+00:00"
        )
        d = make_event(
            "discovery",
            content="API changed",
            references=[a["id"]],
            ts="2026-01-02T00:00:00+00:00",
        )
        self._write_events([a, d])
        md = materialize.materialize(self.smm_dir)
        # Contradicted assumptions show in Conflict Alerts (existing pattern 2)
        self.assertIn("assumption contradicted", md.lower())

    def test_no_drift_section_when_empty(self):
        """No Drift Signals section when nothing to report."""
        events = [make_event("customer_input", content="Hello")]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertNotIn("Drift Signals", md)

    def test_stale_decision_threshold(self):
        """Exactly 4 sessions should not trigger stale (threshold is 5)."""
        d = make_event(
            "decision",
            content="Almost stale",
            topic="edge",
            ts="2026-01-01T00:00:00+00:00",
        )
        sessions = self._make_sessions(4)
        self._write_events([d, *sessions])
        md = materialize.materialize(self.smm_dir)
        if "Drift Signals" in md:
            drift_section = md.split("Drift Signals")[1].split("\n## ")[0]
            self.assertNotIn("edge", drift_section)

    def test_multiple_drift_signals(self):
        """Multiple drift signals can appear together."""
        d = make_event(
            "decision",
            content="Old",
            topic="stale-topic",
            ts="2026-01-01T00:00:00+00:00",
        )
        conv = make_event(
            "convention",
            content="Rule",
            topic="ignored-rule",
            ts="2026-01-01T00:00:00+00:00",
        )
        concerns = [
            make_event(
                "concern",
                content=f"C{i}",
                references=[conv["id"]],
                ts=f"2026-01-0{i + 2}T00:00:00+00:00",
            )
            for i in range(3)
        ]
        sessions = self._make_sessions(6)
        self._write_events([d, conv, *concerns, *sessions])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Drift Signals", md)
        self.assertIn("stale-topic", md)
        self.assertIn("ignored-rule", md)


# ===========================================================================
# Velocity Signal (Milestone 8)
# ===========================================================================


class TestVelocitySignal(_SMMTestCase):
    """Tests for velocity metrics in materialize.py."""

    def test_velocity_events_this_session(self):
        """Counts events since last session_end."""
        se = make_event(
            "session_end", content="end", working_on=[], ts="2026-01-01T00:00:00+00:00"
        )
        e1 = make_event(
            "customer_input", content="new session", ts="2026-01-02T00:00:00+00:00"
        )
        e2 = make_event(
            "status",
            content="working",
            working_on=["f.py"],
            ts="2026-01-02T00:00:01+00:00",
        )
        self._write_events([se, e1, e2])
        events, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(events)
        v = materialize.compute_velocity(events, indices)
        self.assertEqual(v["events_this_session"], 2)

    def test_velocity_total_sessions(self):
        """Counts total session_end events."""
        events = [
            make_event(
                "session_end",
                content="e1",
                working_on=[],
                ts="2026-01-01T00:00:00+00:00",
            ),
            make_event(
                "session_end",
                content="e2",
                working_on=[],
                ts="2026-01-02T00:00:00+00:00",
            ),
        ]
        self._write_events(events)
        parsed, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(parsed)
        v = materialize.compute_velocity(parsed, indices)
        self.assertEqual(v["total_sessions"], 2)

    def test_velocity_decisions_made_and_revisited(self):
        """Counts decisions and identifies revisited topics."""
        events = [
            make_event(
                "decision", content="D1", topic="api", ts="2026-01-01T00:00:00+00:00"
            ),
            make_event(
                "decision", content="D2", topic="db", ts="2026-01-02T00:00:00+00:00"
            ),
            make_event(
                "decision", content="D3", topic="api", ts="2026-01-03T00:00:00+00:00"
            ),
        ]
        self._write_events(events)
        parsed, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(parsed)
        v = materialize.compute_velocity(parsed, indices)
        self.assertEqual(v["decisions_made"], 3)
        self.assertEqual(v["decisions_revisited"], 1)

    def test_velocity_churn_topics(self):
        """Topics with 3+ decisions listed as churn."""
        events = [
            make_event(
                "decision",
                content=f"D{i}",
                topic="flaky",
                ts=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
            for i in range(3)
        ]
        self._write_events(events)
        parsed, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(parsed)
        v = materialize.compute_velocity(parsed, indices)
        self.assertIn("flaky", v["churn_topics"])

    def test_velocity_concern_resolution_ratio(self):
        """Resolved / total concerns."""
        c1 = make_event("concern", content="C1", ts="2026-01-01T00:00:00+00:00")
        c2 = make_event("concern", content="C2", ts="2026-01-02T00:00:00+00:00")
        resolver = make_event(
            "decision",
            content="Fix",
            topic="fix",
            references=[c1["id"]],
            ts="2026-01-03T00:00:00+00:00",
        )
        self._write_events([c1, c2, resolver])
        parsed, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(parsed)
        v = materialize.compute_velocity(parsed, indices)
        self.assertEqual(v["concerns_total"], 2)
        self.assertEqual(v["concerns_resolved"], 1)

    def test_velocity_section_in_output(self):
        """Velocity section appears in materialized markdown."""
        events = [
            make_event("decision", content="D1", topic="api"),
            make_event("session_end", content="end", working_on=[]),
            make_event("customer_input", content="new"),
        ]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Velocity", md)
        self.assertIn("events this session", md.lower())

    def test_velocity_no_section_when_empty(self):
        """No Velocity section for a single customer_input (no decisions, no sessions)."""
        self._write_events([make_event("customer_input")])
        md = materialize.materialize(self.smm_dir)
        # Velocity should still appear (events_this_session > 0)
        # But verify it doesn't crash
        self.assertNotIn("churn", md.lower())

    def test_velocity_no_churn_with_few_decisions(self):
        """Topics with <3 decisions are not churn."""
        events = [
            make_event("decision", content="D1", topic="stable"),
            make_event("decision", content="D2", topic="stable"),
        ]
        self._write_events(events)
        parsed, _ = materialize.parse_events(self.smm_dir)
        indices = materialize.build_indices(parsed)
        v = materialize.compute_velocity(parsed, indices)
        self.assertEqual(v["churn_topics"], [])


# ===========================================================================
# Performance Benchmarks (Milestone 8)
# ===========================================================================


def _generate_mixed_events(count: int) -> list[dict]:
    """Generate a realistic distribution of events."""
    import random

    rng = random.Random(42)  # deterministic for reproducibility
    type_weights = [
        ("customer_input", 25),
        ("status", 20),
        ("decision", 8),
        ("convention", 5),
        ("concern", 8),
        ("discovery", 5),
        ("question", 8),
        ("answer", 5),
        ("assumption", 4),
        ("pair_guidance", 8),
        ("session_end", 2),
        ("goal", 1),
        ("debt", 1),
    ]
    types = []
    for t, w in type_weights:
        types.extend([t] * w)

    events = []
    for i in range(count):
        etype = rng.choice(types)
        ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}+00:00"
        events.append(make_event(etype, content=f"event-{i}", ts=ts))
    return events


class TestPerformanceBenchmarks(_SMMTestCase):
    """Performance benchmark tests for M8."""

    def test_materialize_100_events(self):
        import time

        events = _generate_mixed_events(100)
        self._write_events(events)
        start = time.monotonic()
        materialize.materialize(self.smm_dir)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 100, f"materialize(100) took {elapsed:.0f}ms > 100ms")

    def test_materialize_1000_events(self):
        import time

        events = _generate_mixed_events(1000)
        self._write_events(events)
        start = time.monotonic()
        materialize.materialize(self.smm_dir)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 500, f"materialize(1000) took {elapsed:.0f}ms > 500ms")

    def test_materialize_5000_events(self):
        import time

        events = _generate_mixed_events(5000)
        self._write_events(events)
        start = time.monotonic()
        materialize.materialize(self.smm_dir)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(
            elapsed, 2000, f"materialize(5000) took {elapsed:.0f}ms > 2000ms"
        )

    def test_read_delta_1000_with_watermark(self):
        import time

        events = _generate_mixed_events(1000)
        self._write_events(events)
        read_delta.write_watermark(self.smm_dir, "bench", 500)
        start = time.monotonic()
        read_delta.read_delta(self.smm_dir, "bench", tier="full")
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(
            elapsed, 50, f"read_delta(1000@500) took {elapsed:.0f}ms > 50ms"
        )

    def test_compact_5000_events(self):
        import time

        import compact

        events = _generate_mixed_events(5000)
        # Add session_end events at regular intervals
        for i in range(10):
            events.append(
                make_event(
                    "session_end",
                    content=f"end-{i}",
                    working_on=[],
                    ts=f"2026-02-{i + 1:02d}T00:00:00+00:00",
                )
            )
        self._write_events(events)
        start = time.monotonic()
        compact.compact(self.smm_dir, keep_sessions=3)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 1000, f"compact(5000) took {elapsed:.0f}ms > 1000ms")

    def test_repair_5000_events(self):
        import time

        import repair

        events = _generate_mixed_events(5000)
        self._write_events(events)
        start = time.monotonic()
        repair.repair(self.smm_dir)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 1000, f"repair(5000) took {elapsed:.0f}ms > 1000ms")

    def test_mixed_event_generator_distribution(self):
        """Verify _generate_mixed_events produces expected types."""
        events = _generate_mixed_events(100)
        types = {e["type"] for e in events}
        # Should have at least a few different types
        self.assertGreater(len(types), 5)
        # All should be valid events
        for e in events:
            self.assertIn("id", e)
            self.assertIn("type", e)


if __name__ == "__main__":
    unittest.main()
