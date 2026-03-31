#!/usr/bin/env python3
"""Tests for parsing, index building logic.

Resolution tests in test_resolutions.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
import materialize
from conftest import _SMMTestCase, make_event

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
        import fcntl

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


if __name__ == "__main__":
    unittest.main()
