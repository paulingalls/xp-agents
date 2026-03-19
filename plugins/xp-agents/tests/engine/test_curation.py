#!/usr/bin/env python3
"""Tests for bulk operations, curation data preparation, and atomic writes.

Split from smm/test_engine.py — covers:
  TestBulkAppend, TestPrepareCurationData, TestWriteAtomic.
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

    def test_resolved_assumption_excluded_from_risks(self):
        """Resolved assumptions are excluded from current_smm.risks."""
        assumption = make_event("assumption", content="API returns JSON")
        resolver = make_event(
            "status",
            content="Verified",
            working_on=[],
            metadata={"resolves": [assumption["id"]]},
        )
        self._write_events([assumption, resolver])
        result = materialize.prepare_curation_data(self.smm_dir)
        risk_ids = {r["id"] for r in result["current_smm"]["risks"]}
        self.assertNotIn(assumption["id"], risk_ids)

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
