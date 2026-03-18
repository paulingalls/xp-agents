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
import _append_impl  # noqa: I001
import materialize
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
# parse_jsonl — Shared JSONL parsing
# ===========================================================================


class TestParseJsonl(unittest.TestCase):
    """Tests for _append_impl.parse_jsonl()."""

    def test_empty_string(self):
        events, skipped = _append_impl.parse_jsonl("")
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_blank_lines_only(self):
        events, skipped = _append_impl.parse_jsonl("\n\n  \n")
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_valid_events(self):
        raw = '{"id": "a", "type": "status"}\n{"id": "b", "type": "goal"}\n'
        events, skipped = _append_impl.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["id"], "a")
        self.assertEqual(events[1]["id"], "b")
        self.assertEqual(skipped, 0)

    def test_malformed_json_skipped(self):
        raw = '{"id": "a"}\nnot-json\n{"id": "b"}\n'
        events, skipped = _append_impl.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)

    def test_non_dict_skipped(self):
        raw = '{"id": "a"}\n[1, 2, 3]\n"just a string"\n{"id": "b"}\n'
        events, skipped = _append_impl.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 2)

    def test_mixed_valid_and_invalid(self):
        raw = '{"ok": true}\n\nbad\n{"ok": false}\n'
        events, skipped = _append_impl.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)


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
            with self.assertRaises(_append_impl.LockTimeoutError):
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
            working_on=["test.py"],
            metadata={"resolves": [c["id"]]},
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
# Resolution via metadata.resolves
# ===========================================================================


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

    def test_resolve_prefix_ambiguous_skipped(self):
        """If a prefix matches multiple events, skip it (ambiguous)."""
        # Create two concerns with the same 8-char prefix (unlikely in
        # practice but we should handle it gracefully).
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
        read_delta.read_delta(self.smm_dir, "main")
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "new")

    def test_watermark_advances(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 1)

    def test_watermark_beyond_file_empty_result(self):
        self._write_events([make_event()])
        read_delta.write_watermark(self.smm_dir, "main", 100)
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 0)

    def test_no_update_flag(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", update_watermark=False)
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_missing_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        events = read_delta.read_delta(fake_dir, "main")
        self.assertEqual(len(events), 0)

    def test_empty_file(self):
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 0)

    def test_multiple_agents_independent_watermarks(self):
        self._write_events([make_event(), make_event(), make_event()])
        read_delta.read_delta(self.smm_dir, "alice")
        # Alice at 3, bob at 0
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        alice_events = read_delta.read_delta(self.smm_dir, "alice")
        bob_events = read_delta.read_delta(self.smm_dir, "bob")
        self.assertEqual(len(alice_events), 1)
        self.assertEqual(len(bob_events), 4)


# ===========================================================================
# Compact (Milestone 8)
# ===========================================================================


class TestCompact(_SMMTestCase):
    """Tests for compact() legacy entry point (delegates to compact_after_curation)."""

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

    def test_compact_delegates_to_compact_after_curation(self):
        """compact() uses curation-watermark-based retention via delegation."""
        import compact

        goal = make_event("goal", content="keep me", ts="2026-01-01T00:00:00+00:00")
        filler = make_event("status", content="discard", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, filler, session_end, new_event])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        result = compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Unresolved goal retained (SMM-referenced)
        self.assertIn(goal["id"], retained_ids)
        # Filler archived
        self.assertNotIn(filler["id"], retained_ids)
        # Return has legacy keys
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)

    def test_compact_unresolved_questions_retained(self):
        """Unresolved questions retained via SMM-referenced policy."""
        import compact

        q = make_event(
            "question",
            content="Unanswered?",
            priority="🔴",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event("status", content="filler", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([q, filler, session_end])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(q["id"], retained_ids)

    def test_compact_resolved_questions_archivable(self):
        """Resolved questions before watermark can be archived."""
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
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([q, a, session_end])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(q["id"], retained_ids)

    def test_compact_unresolved_concerns_retained(self):
        """Unresolved concerns retained via SMM-referenced policy."""
        import compact

        c = make_event(
            "concern", content="Unresolved concern", ts="2026-01-01T00:00:00+00:00"
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([c, session_end])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(c["id"], retained_ids)

    def test_compact_creates_archive(self):
        """Archived events written to backups/archive-{ts}.jsonl."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeping")

        compact.compact(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_compact_removes_orphaned_watermarks(self):
        """Orphaned .watermark-* files removed, prompt-nugget reset."""
        import compact

        self._write_events(self._make_session(session_num=1))
        materialize.write_curation_watermark(self.smm_dir, 4, "xp-housekeeping")
        (self.smm_dir / ".watermark-main").write_text("5")
        (self.smm_dir / ".watermark-navigator").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact(self.smm_dir)
        # Orphaned removed
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        self.assertFalse((self.smm_dir / ".watermark-navigator").exists())
        # Prompt-nugget preserved with updated value
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())

    def test_compact_atomic_replacement(self):
        """events.jsonl is replaced atomically (not corrupted on crash)."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        materialize.write_curation_watermark(
            self.smm_dir, len(events), "xp-housekeeping"
        )
        compact.compact(self.smm_dir)
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)  # Should not raise

    def test_compact_no_watermark_no_archival(self):
        """Without curation watermark, nothing is archived."""
        import compact

        self._write_events(self._make_session(session_num=1))
        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)

    def test_compact_returns_counts(self):
        """Return dict has archived, retained, permanent keys."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeping")

        result = compact.compact(self.smm_dir)
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)
        self.assertEqual(
            result["archived"] + result["retained"],
            len(old) + 1,
        )

    def test_compact_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        decision = make_event(
            "decision", content="first", topic="t", ts="2026-01-01T00:00:00+00:00"
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([decision, session_end, new_event])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        self.assertEqual(ids[0], decision["id"])


# ===========================================================================
# Compact After Curation (Milestone 6)
# ===========================================================================


class TestCompactAfterCuration(_SMMTestCase):
    """Tests for curation-watermark-based compaction."""

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

    def _set_curation_watermark(
        self, event_count: int, agent_id: str = "xp-housekeeping"
    ):
        """Write a curation watermark at the given event count."""
        materialize.write_curation_watermark(self.smm_dir, event_count, agent_id)

    def test_keeps_events_after_curation_watermark(self):
        """Events past the curation watermark are always retained."""
        import compact

        old = self._make_session(session_num=1)
        new = self._make_session(session_num=2)
        self._write_events(old + new)
        self._set_curation_watermark(len(old))  # watermark at boundary

        result = compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_contents = [e.get("content", "") for e in retained]
        # All "new" session events retained
        for e in new:
            self.assertIn(e["content"], retained_contents)
        self.assertGreater(result["archived"], 0)

    def test_keeps_last_3_session_ends(self):
        """Last 3 session_end events retained for aging calculations."""
        import compact

        all_events = []
        for s in range(1, 7):  # 6 sessions
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)
        # Watermark after session 5, so session 6 events are post-watermark
        wm = sum(4 for _ in range(5))  # 5 sessions * 4 events each
        self._set_curation_watermark(wm)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        session_ends = [e for e in retained if e.get("type") == "session_end"]
        # Should have session 6 (post-watermark) + 3 oldest retained = at least 3 pre-watermark
        pre_wm_ends = [
            e for e in session_ends if e.get("content", "") != "end session 6"
        ]
        self.assertGreaterEqual(len(pre_wm_ends), 3)

    def test_keeps_smm_referenced_events(self):
        """Unresolved goals, active decisions, open concerns are retained."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        decision = make_event(
            "decision",
            content="Use Postgres",
            topic="db",
            ts="2026-01-01T00:00:00+00:00",
        )
        concern = make_event(
            "concern",
            content="No tests",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event("status", content="working", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([goal, decision, concern, filler, session_end])
        self._set_curation_watermark(5)  # all pre-watermark

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(goal["id"], retained_ids)
        self.assertIn(decision["id"], retained_ids)
        self.assertIn(concern["id"], retained_ids)
        # Filler status should be archived
        self.assertNotIn(filler["id"], retained_ids)

    def test_archives_resolved_permanent_before_watermark(self):
        """Resolved goal before watermark is archivable (new policy)."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        resolution = make_event(
            "status",
            content="Goal completed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [goal["id"]]},
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-03T00:00:00+00:00", working_on=[]
        )
        new_event = make_event(
            "status", content="new work", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([goal, resolution, session_end, new_event])
        self._set_curation_watermark(3)  # watermark before new_event

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Resolved goal is archivable
        self.assertNotIn(goal["id"], retained_ids)

    def test_keeps_resolution_events(self):
        """If a goal is retained, its resolving event is also retained."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        # Goal is unresolved — no resolution event
        concern = make_event(
            "concern", content="Open issue", ts="2026-01-01T00:00:00+00:00"
        )
        partial_resolution = make_event(
            "status",
            content="Partially addressed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [concern["id"]]},
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-03T00:00:00+00:00", working_on=[]
        )
        self._write_events([goal, concern, partial_resolution, session_end])
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Goal is unresolved — retained
        self.assertIn(goal["id"], retained_ids)
        # Concern is resolved — not retained
        self.assertNotIn(concern["id"], retained_ids)
        # Resolution event for concern — not retained (concern is resolved)
        self.assertNotIn(partial_resolution["id"], retained_ids)

    def test_creates_backup_archive(self):
        """Archived events written to backups/ directory."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*all_events, new_event])
        self._set_curation_watermark(len(all_events))

        compact.compact_after_curation(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        goal = make_event("goal", content="first", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        # Goal (unresolved) should come before session_end and new_event
        self.assertEqual(ids[0], goal["id"])

    def test_no_watermark_keeps_all(self):
        """No curation watermark = no compaction."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        # No watermark set

        result = compact.compact_after_curation(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        retained = self._read_events()
        self.assertEqual(len(retained), len(events))

    def test_resets_prompt_nugget_watermark(self):
        """Prompt-nugget watermark set to post-compaction event count."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*all_events, new_event])
        # Create an old prompt-nugget watermark at a high value
        (self.smm_dir / ".watermark-prompt-nugget").write_text("100")
        self._set_curation_watermark(len(all_events))

        result = compact.compact_after_curation(self.smm_dir)
        self.assertGreater(result["archived"], 0)
        # Watermark should be reset to retained count
        wm_text = (self.smm_dir / ".watermark-prompt-nugget").read_text().strip()
        self.assertEqual(int(wm_text), result["retained"])

    def test_updates_curation_watermark(self):
        """Curation watermark event_count updated after compaction."""
        import compact

        goal = make_event("goal", content="Keep me", ts="2026-01-01T00:00:00+00:00")
        filler = make_event("status", content="discard", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, filler, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        wm = materialize.read_curation_watermark(self.smm_dir)
        # Curation watermark should point to the boundary between
        # retained pre-watermark events and post-watermark events
        retained = self._read_events()
        post_wm_count = 1  # new_event
        self.assertEqual(wm["event_count"], len(retained) - post_wm_count)

    def test_removes_orphaned_watermarks(self):
        """Orphaned .watermark-{hex} files removed, prompt-nugget preserved."""
        import compact

        self._write_events(self._make_session(session_num=1))
        self._set_curation_watermark(4)
        # Create orphaned watermarks
        (self.smm_dir / ".watermark-abc123").write_text("5")
        (self.smm_dir / ".watermark-main").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact_after_curation(self.smm_dir)
        # Orphaned watermarks removed
        self.assertFalse((self.smm_dir / ".watermark-abc123").exists())
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        # Prompt-nugget preserved (with updated value)
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())
        # Curation watermark preserved
        self.assertTrue((self.smm_dir / ".curation-watermark").exists())

    def test_team_safety_uses_oldest_watermark(self):
        """With multiple curation watermarks, uses min(event_count)."""
        import compact

        all_events = []
        for s in range(1, 4):
            all_events.extend(self._make_session(session_num=s))
        filler = make_event("status", content="extra", ts="2026-03-04T00:00:00+00:00")
        all_events.append(filler)
        self._write_events(all_events)

        # Agent A curated up to event 8, agent B only up to event 4
        materialize.write_curation_watermark(self.smm_dir, 8, "agent-a")
        # Overwrite with agent B's older watermark to simulate team
        # For now, we test by writing a second watermark file
        wm_b = self.smm_dir / ".curation-watermark-agent-b"
        wm_b.write_text(json.dumps({"event_count": 4, "agent_id": "agent-b"}))

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        # Should retain everything from event 4 onward (agent B's boundary)
        # = 3 sessions * 4 events + 1 filler - 4 = 9 post-watermark events
        # Plus any SMM-referenced or session_ends from pre-watermark
        self.assertGreaterEqual(len(retained), len(all_events) - 4)


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

    def test_read_delta_1000_with_watermark(self):
        import time

        events = _generate_mixed_events(1000)
        self._write_events(events)
        read_delta.write_watermark(self.smm_dir, "bench", 500)
        start = time.monotonic()
        read_delta.read_delta(self.smm_dir, "bench")
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


class TestBulkAppend(_SMMTestCase):
    """Tests for bulk_append() — multi-event atomic writes."""

    def test_bulk_append_empty_noop(self):
        """Empty list should not touch events.jsonl or acquire lock."""
        _append_impl.bulk_append(self.smm_dir, [])
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertEqual(content, "")

    def test_bulk_append_multiple_events(self):
        """Three valid events should all appear in events.jsonl."""
        events = [
            make_event("status", content=f"Status {i}", working_on=[]) for i in range(3)
        ]
        _append_impl.bulk_append(self.smm_dir, events)
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            self.assertEqual(parsed["id"], events[i]["id"])

    def test_bulk_append_strips_ansi(self):
        """ANSI escape codes should be stripped from content."""
        event = make_event(
            "status",
            content="\x1b[31mRed text\x1b[0m",
            working_on=[],
        )
        _append_impl.bulk_append(self.smm_dir, [event])
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["content"], "Red text")

    def test_bulk_append_validates_all_before_write(self):
        """If any event is invalid, none should be written."""
        good = make_event("status", content="OK", working_on=[])
        bad = {"type": "status", "content": "no id"}  # missing required fields
        with self.assertRaises(ValueError):
            _append_impl.bulk_append(self.smm_dir, [good, bad])
        content = (self.smm_dir / "events.jsonl").read_text()
        self.assertEqual(content, "")

    def test_bulk_append_appends_to_existing(self):
        """bulk_append should append, not overwrite existing events."""
        existing = make_event("customer_input", content="First")
        _append_impl.append_event(self.smm_dir, existing)
        new_events = [
            make_event("status", content="Second", working_on=[]),
        ]
        _append_impl.bulk_append(self.smm_dir, new_events)
        lines = (self.smm_dir / "events.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)


# ---------------------------------------------------------------------------
# Curation watermark tests (M1)
# ---------------------------------------------------------------------------


class TestCurationWatermark(_SMMTestCase):
    """Tests for curation watermark read/write."""

    def test_no_watermark_returns_defaults(self):
        """Missing .curation-watermark returns default dict."""
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["timestamp"], "")
        self.assertEqual(result["agent_id"], "")

    def test_write_and_read_roundtrip(self):
        """Write then read returns correct values."""
        materialize.write_curation_watermark(self.smm_dir, 42, "xp-housekeeping")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 42)
        self.assertEqual(result["agent_id"], "xp-housekeeping")
        # timestamp should be a non-empty ISO8601 string
        self.assertTrue(len(result["timestamp"]) > 0)

    def test_corrupted_watermark_returns_defaults(self):
        """Garbage in .curation-watermark returns defaults."""
        wm_file = self.smm_dir / ".curation-watermark"
        wm_file.write_text("not json at all {{{")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["timestamp"], "")
        self.assertEqual(result["agent_id"], "")

    def test_watermark_file_permissions(self):
        """Written watermark has mode 0o600."""
        materialize.write_curation_watermark(self.smm_dir, 10, "test")
        wm_file = self.smm_dir / ".curation-watermark"
        mode = wm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_overwrite_reads_latest(self):
        """Second write overwrites; read returns second value."""
        materialize.write_curation_watermark(self.smm_dir, 10, "agent-a")
        materialize.write_curation_watermark(self.smm_dir, 50, "agent-b")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 50)
        self.assertEqual(result["agent_id"], "agent-b")


# ---------------------------------------------------------------------------
# prepare_curation_data tests (M1)
# ---------------------------------------------------------------------------


class TestPrepareCurationData(_SMMTestCase):
    """Tests for prepare_curation_data()."""

    # -- Step 2: Fresh project --

    def test_fresh_project_empty(self):
        """Empty events.jsonl returns valid structure with empty fields."""
        result = materialize.prepare_curation_data(self.smm_dir)
        for key in (
            "current_smm",
            "new_since_last_curation",
            "retro_history",
            "aging",
            "health",
        ):
            self.assertIn(key, result)
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertEqual(result["current_smm"][pillar], [])
        for key in ("intent_count", "constraints_count", "risks_count", "wisdom_count"):
            self.assertEqual(result["health"][key], 0)

    def test_no_watermark_all_events_new(self):
        """Without watermark, all events appear in new_since_last_curation."""
        events = [
            make_event("customer_input", content="Build an API"),
            make_event(
                "decision", topic="db", content="Use Postgres", metadata={"draft": True}
            ),
            make_event("concern", content="No tests yet"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(len(new["decisions"]), 1)
        self.assertEqual(len(new["concerns"]), 1)

    # -- Step 3: Mature project --

    def test_watermark_splits_old_new(self):
        """Events after watermark go to new_since; older events feed current_smm."""
        old_events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", topic="auth", content="Use JWT"),
            make_event("convention", topic="api", content="REST only"),
        ]
        new_events = [
            make_event("customer_input", content="Add password reset"),
            make_event("concern", content="Empty catch block"),
        ]
        self._write_events(old_events + new_events)
        materialize.write_curation_watermark(
            self.smm_dir, len(old_events), "xp-housekeeping"
        )
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(new["customer_inputs"][0]["content"], "Add password reset")
        self.assertEqual(len(new["concerns"]), 1)
        # Old decisions should NOT be in new
        self.assertEqual(len(new["decisions"]), 0)

    def test_current_smm_intent(self):
        """current_smm.intent contains unresolved goals and open intents."""
        events = [
            make_event("goal", content="Ship v1"),
            make_event("customer_intent", content="Add RBAC", intent_status="open"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        intents = result["current_smm"]["intent"]
        self.assertEqual(len(intents), 2)

    def test_current_smm_constraints(self):
        """current_smm.constraints = non-draft decisions + conventions."""
        events = [
            make_event("decision", topic="db", content="Use Postgres"),
            make_event(
                "decision", topic="hash", content="Use bcrypt", metadata={"draft": True}
            ),
            make_event("convention", topic="api", content="REST only"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        constraints = result["current_smm"]["constraints"]
        # Only non-draft decision + convention = 2
        self.assertEqual(len(constraints), 2)
        contents = [c["content"] for c in constraints]
        self.assertIn("Use Postgres", contents)
        self.assertIn("REST only", contents)
        self.assertNotIn("Use bcrypt", contents)

    def test_current_smm_risks(self):
        """current_smm.risks = unresolved concerns + assumptions + debt + questions."""
        events = [
            make_event("concern", content="No tests"),
            make_event("assumption", content="Users prefer REST"),
            make_event("debt", content="Legacy code", files=["old.py"]),
            make_event("question", content="Which DB?", priority="\U0001f534"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        risks = result["current_smm"]["risks"]
        self.assertEqual(len(risks), 4)

    def test_resolved_items_excluded_from_current_smm(self):
        """Resolved goals/concerns/debt excluded from current_smm."""
        goal = make_event("goal", content="Ship v1")
        concern = make_event("concern", content="Old bug")
        resolver_g = make_event(
            "status", content="Done", working_on=[], metadata={"resolves": [goal["id"]]}
        )
        resolver_c = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([goal, concern, resolver_g, resolver_c])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(len(result["current_smm"]["intent"]), 0)
        self.assertEqual(len(result["current_smm"]["risks"]), 0)

    def test_aging_counts_sessions(self):
        """Aging dict maps risk IDs to session count since creation."""
        concern = make_event(
            "concern", content="No tests", ts="2026-01-01T00:00:00+00:00"
        )
        sessions = [
            make_event(
                "session_end",
                content=f"end {i}",
                ts=f"2026-03-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(4)
        ]
        self._write_events([concern, *sessions])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["aging"][concern["id"]], 4)

    def test_resolutions_after_watermark(self):
        """Resolutions after watermark appear in new_since_last_curation."""
        concern = make_event("concern", content="Bug")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=[],
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolver])
        materialize.write_curation_watermark(self.smm_dir, 1, "xp-housekeeping")
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn(concern["id"], result["new_since_last_curation"]["resolutions"])

    def test_health_counts(self):
        """Health section counts items in each pillar."""
        events = [
            make_event("goal", content="G1"),
            make_event("goal", content="G2"),
            make_event("customer_intent", content="I1", intent_status="open"),
            make_event("decision", topic="db", content="Use PG"),
            make_event("convention", topic="api", content="REST"),
            make_event("concern", content="C1"),
            make_event("assumption", content="A1"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertEqual(result["health"]["intent_count"], 3)
        self.assertEqual(result["health"]["constraints_count"], 2)
        self.assertEqual(result["health"]["risks_count"], 2)

    # -- Step 4: retro_history + team --

    def test_retro_history_latest_tries(self):
        """latest_tries from most recent retrospective."""
        r1 = make_event(
            "retrospective",
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "Good tests"}],
            fix=[{"content": "Slow deploys"}],
        )
        r1["try"] = [{"content": "Split commits"}]
        r2 = make_event(
            "retrospective",
            content="Retro 2",
            ts="2026-02-01T00:00:00+00:00",
            keep=[{"content": "TDD held"}],
            fix=[{"content": "Big commits"}],
        )
        r2["try"] = [{"content": "Add lint"}, {"content": "Grep before remove"}]
        self._write_events([r1, r2])
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn("Add lint", result["retro_history"]["latest_tries"])
        self.assertIn("Grep before remove", result["retro_history"]["latest_tries"])
        self.assertNotIn("Split commits", result["retro_history"]["latest_tries"])

    def test_retro_history_adopted_tries(self):
        """Tries from earlier retros not in any fix list are adopted."""
        r1 = make_event(
            "retrospective",
            content="Retro 1",
            ts="2026-01-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "Bad deploys"}],
        )
        r1["try"] = [{"content": "Use CI"}, {"content": "Split commits"}]
        r2 = make_event(
            "retrospective",
            content="Retro 2",
            ts="2026-02-01T00:00:00+00:00",
            keep=[{"content": "ok"}],
            fix=[{"content": "Split commits"}],
        )  # "Split commits" appeared as fix
        r2["try"] = [{"content": "Add lint"}]
        self._write_events([r1, r2])
        result = materialize.prepare_curation_data(self.smm_dir)
        adopted = result["retro_history"]["adopted_tries"]
        # "Use CI" was tried in r1 and never appeared as a fix — adopted
        self.assertIn("Use CI", adopted)
        # "Split commits" was tried in r1 but appeared as a fix in r2 — NOT adopted
        self.assertNotIn("Split commits", adopted)

    def test_retro_history_recurring_fixes(self):
        """Fix items appearing in 3+ retros are recurring."""
        retros = []
        for i in range(3):
            r = make_event(
                "retrospective",
                content=f"Retro {i}",
                ts=f"2026-0{i + 1}-01T00:00:00+00:00",
                keep=[{"content": "ok"}],
                fix=[{"content": "Big commits"}, {"content": f"Unique {i}"}],
            )
            r["try"] = [{"content": "try something"}]
            retros.append(r)
        self._write_events(retros)
        result = materialize.prepare_curation_data(self.smm_dir)
        self.assertIn("Big commits", result["retro_history"]["recurring_fixes"])
        self.assertNotIn("Unique 0", result["retro_history"]["recurring_fixes"])

    def test_team_scenario_multiple_agents(self):
        """Events from multiple agents all feed into curation data."""
        events = [
            make_event("customer_input", content="Input from A", agent_id="agent-a"),
            make_event(
                "decision",
                topic="db",
                content="Use PG",
                agent_id="agent-a",
                metadata={"draft": True},
            ),
            make_event("concern", content="No tests", agent_id="agent-b"),
        ]
        self._write_events(events)
        result = materialize.prepare_curation_data(self.smm_dir)
        new = result["new_since_last_curation"]
        self.assertEqual(len(new["customer_inputs"]), 1)
        self.assertEqual(len(new["decisions"]), 1)
        self.assertEqual(len(new["concerns"]), 1)


# ===========================================================================
# write_text_atomic / write_json_atomic — Shared atomic write utilities
# ===========================================================================


class TestWriteAtomic(_SMMTestCase):
    """Tests for _append_impl.write_text_atomic() and write_json_atomic()."""

    def test_write_text_creates_file(self):
        """write_text_atomic creates a new file with expected content."""
        target = self.smm_dir / "hello.txt"
        _append_impl.write_text_atomic(target, "hello world")
        self.assertEqual(target.read_text(), "hello world")

    def test_write_text_overwrites(self):
        """write_text_atomic overwrites existing file with latest content."""
        target = self.smm_dir / "overwrite.txt"
        _append_impl.write_text_atomic(target, "first")
        _append_impl.write_text_atomic(target, "second")
        self.assertEqual(target.read_text(), "second")

    def test_write_text_permissions(self):
        """write_text_atomic sets file permissions to 0o600."""
        target = self.smm_dir / "perms.txt"
        _append_impl.write_text_atomic(target, "secret")
        mode = target.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_write_text_no_temp_files(self):
        """write_text_atomic leaves no .tmp files behind."""
        target = self.smm_dir / "clean.txt"
        _append_impl.write_text_atomic(target, "data")
        tmp_files = list(self.smm_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_write_json_roundtrip(self):
        """write_json_atomic writes JSON that round-trips correctly."""
        target = self.smm_dir / "data.json"
        data = {"key": "value", "count": 42, "nested": {"a": [1, 2, 3]}}
        _append_impl.write_json_atomic(target, data)
        import json as _json

        loaded = _json.loads(target.read_text())
        self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
