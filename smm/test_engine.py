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

    def test_decisions_section(self):
        d = make_event("decision", topic="db", content="Use Postgres", agent_id="nav")
        self._write_events([d])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Architecture Decisions", md)
        self.assertIn("**Use Postgres**", md)
        self.assertIn("nav", md)

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

    def test_question_blocking(self):
        q = make_event("question", priority="\U0001f534", content="Which framework?")
        self._write_events([q])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Questions for Customer", md)
        self.assertIn("\U0001f534", md)
        self.assertIn("blocking, awaiting answer", md)

    def test_question_answered(self):
        q = make_event("question", priority="\U0001f534", content="Which DB?")
        a = make_event("answer", content="Postgres", references=[q["id"]])
        self._write_events([q, a])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("✅", md)
        self.assertIn("answered: Postgres", md)

    def test_question_assumed(self):
        q = make_event("question", priority="\U0001f7e1", content="Auth method?")
        assumption = make_event(
            "assumption", content="Using OAuth", references=[q["id"]]
        )
        self._write_events([q, assumption])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("🟡", md)
        self.assertIn("assumed: Using OAuth", md)

    def test_customer_input_last_5(self):
        events = [make_event("customer_input", content=f"Input {i}") for i in range(7)]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Customer Input", md)
        self.assertNotIn("Input 0", md)
        self.assertNotIn("Input 1", md)
        self.assertIn("Input 2", md)
        self.assertIn("Input 6", md)
        self.assertIn("showing last 5 of 7", md)

    def test_customer_input_5_or_fewer_no_message(self):
        events = [make_event("customer_input", content=f"Input {i}") for i in range(3)]
        self._write_events(events)
        md = materialize.materialize(self.smm_dir)
        self.assertIn("Input 0", md)
        self.assertNotIn("showing last", md)

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

    def test_concerns_unacknowledged(self):
        c = make_event("concern", content="Missing error handling")
        self._write_events([c])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("## Concerns", md)
        self.assertIn("⚠️", md)
        self.assertIn("unacknowledged", md)

    def test_concerns_resolved(self):
        c = make_event("concern", content="Missing tests")
        r = make_event(
            "status", content="Fixed", references=[c["id"]], working_on=["test.py"]
        )
        self._write_events([c, r])
        md = materialize.materialize(self.smm_dir)
        self.assertIn("✅", md)
        self.assertIn("resolved", md)

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
        # Agent Status section shows only latest — First task shouldn't be in that section
        status_section = md.split("## Agent Status")[1].split("##")[0]
        self.assertNotIn("First task", status_section)

    def test_navigator_guidance_last_3(self):
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
        self.assertNotIn("## Concerns", md)
        self.assertNotIn("## Conflict Alerts", md)
        self.assertNotIn("## Navigator Guidance", md)
        self.assertNotIn("## Unknown Events", md)

    def test_all_12_types_render(self):
        q = make_event("question", content="Q?", priority="\U0001f534")
        events = [
            make_event("customer_input", content="Hello"),
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
        self.assertIn("12 events", md)

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

    def test_no_temp_files_left(self):
        self._write_events([make_event()])
        materialize.materialize_to_file(self.smm_dir)
        tmp_files = list(self.smm_dir.glob("*.md.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_overwrites_existing(self):
        self._write_events([make_event("customer_input", content="First")])
        materialize.materialize_to_file(self.smm_dir)
        self._write_events([make_event("customer_input", content="Second")])
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
        self.assertIn("--- SMM Delta (1 new events) ---", result)
        self.assertIn("--- End SMM Delta ---", result)

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


if __name__ == "__main__":
    unittest.main()
