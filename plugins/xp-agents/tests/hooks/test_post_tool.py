#!/usr/bin/env python3
"""Tests for PostToolUse hook (post_tool_use.py).

Split from the original monolithic test_post_tool.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import post_tool_use
from conftest import _HookTestCase, _make_write_input, make_event

# ===========================================================================
# post_tool_use.py tests — Milestone 3.3
# ===========================================================================


class TestPostToolUse(_HookTestCase):
    def test_auto_status_from_write(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        # Path is normalized against cwd
        self.assertIn("/tmp/src/app.ts", statuses[0]["working_on"])

    def test_auto_status_from_edit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_auto_status_from_multiedit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_normalizes_relative_path(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}, cwd="/home/user"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(statuses[0]["working_on"], ["/home/user/src/app.ts"])

    def test_xp_agent_skips(self):
        post_tool_use.run(
            _make_write_input(agent_type="xp-housekeeper"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        post_tool_use.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_auto_status_carries_file_write_action(self):
        """sprint-042 M2: auto-status carries metadata.action=file_write
        + metadata.files=[normalized] so consumers can read structured
        fields without parsing 'Wrote to ...' content."""
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "file_write")
        self.assertEqual(metadata.get("files"), ["/tmp/src/app.ts"])

    def test_metadata_files_uses_normalized_path(self):
        """metadata.files[0] must equal the same normalized path that the
        content string uses — single source of truth, no drift."""
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}, cwd="/home/user"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        normalized = "/home/user/src/app.ts"
        self.assertEqual(statuses[0]["working_on"], [normalized])
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("files"), [normalized])
        self.assertIn(normalized, statuses[0].get("content", ""))

    def test_conflict_working_on_overlap(self):
        # Another agent claims the same file
        self._write_events(
            [
                make_event("status", agent_id="other", working_on=["src/app.ts"]),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_conflict_stale_question(self):
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        self._write_events([q, *filler])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("stale" in c["content"].lower() for c in concerns))

    def test_conflict_superseded_decision(self):
        self._write_events(
            [
                make_event("decision", topic="db", content="Use Postgres"),
                make_event("decision", topic="db", content="Use MySQL"),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("superseded" in c["content"].lower() for c in concerns))

    def test_conflict_assumption_contradicted(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._write_events([a, d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_conflict_convention_violation(self):
        self._write_events(
            [
                make_event("convention", topic="naming", content="Use camelCase"),
                make_event("decision", topic="naming", content="Use snake_case"),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("convention" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [
                make_event("status", agent_id="main", working_on=["src/a.ts"]),
                make_event("decision", topic="db", content="Use Postgres"),
            ]
        )
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/b.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_semantic_references(self):
        # Decision references our file
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/auth.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/auth.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        refs = statuses[0].get("references", [])
        self.assertIn(d["id"], refs)

    def test_no_semantic_refs_unrelated(self):
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/other.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        refs = statuses[0].get("references", [])
        self.assertNotIn(d["id"], refs)


# ===========================================================================
# hooks.json PostToolUse registration — Milestone 3.3
# ===========================================================================


class TestPostToolUseHooksConfig(unittest.TestCase):
    def test_hooks_json_has_post_tool_use(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("PostToolUse", data["hooks"])

    def test_post_tool_use_write_matcher(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Write|Edit|MultiEdit", matchers)

    def test_post_tool_use_bash_matcher(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Bash", matchers)


import post_tool_exit_plan  # noqa: E402


class TestPostToolExitPlan(_HookTestCase):
    """PostToolUse:ExitPlanMode writes marker, event, and returns context."""

    def test_returns_review_nudge(self):
        """Should return additionalContext nudging /xp-review-plan."""
        result = post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-review-plan", result)

    def test_writes_marker_file(self):
        """Should create .plan-awaiting-review marker."""
        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertTrue(marker.exists())

    def test_writes_gate_event(self):
        """Should append plan_awaiting_review status event."""
        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)

    def test_skips_xp_agents(self):
        """XP agent types should be skipped."""
        result = post_tool_exit_plan.run(
            {
                "session_id": "t",
                "agent_id": "main",
                "agent_type": "xp-test",
                "tool_name": "ExitPlanMode",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertFalse(marker.exists())

    def test_no_smm_dir_returns_none(self):
        """Missing SMM dir should return None gracefully."""
        result = post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=Path("/nonexistent/path"),
        )
        self.assertIsNone(result)

    def test_marker_contains_plan_path_from_tool_response(self):
        """Marker should contain the filePath from ExitPlanMode tool_response."""
        import markers

        plan_path = "/home/user/.claude/plans/my-plan.md"
        post_tool_exit_plan.run(
            {
                "session_id": "t",
                "agent_id": "main",
                "tool_name": "ExitPlanMode",
                "tool_response": {"filePath": plan_path},
            },
            smm_dir=self.smm_dir,
        )
        content = markers.marker_read(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self.assertEqual(content, plan_path)

    def test_marker_falls_back_to_agent_id_without_tool_response(self):
        """Without tool_response, marker should contain agent_id as fallback."""
        import markers

        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        content = markers.marker_read(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self.assertEqual(content, "main")


if __name__ == "__main__":
    unittest.main()
