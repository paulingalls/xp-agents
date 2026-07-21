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
from event_helpers import events_of_type

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)

_WATERMARK_ID = "test-post-tool"

# ===========================================================================
# post_tool_use.py tests — Milestone 3.3
# ===========================================================================


class TestPostToolUse(_HookTestCase):
    def test_auto_status_from_write(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1)

    def test_normalizes_relative_path(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}, cwd="/home/user"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(statuses[0]["working_on"], ["/home/user/src/app.ts"])

    def test_xp_agent_skips(self):
        post_tool_use.run(
            _make_write_input(agent_type="xp-housekeeper"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        normalized = "/home/user/src/app.ts"
        self.assertEqual(statuses[0]["working_on"], [normalized])
        metadata = statuses[0].get("metadata") or {}
        self.assertEqual(metadata.get("files"), [normalized])
        self.assertIn(normalized, statuses[0].get("content", ""))

    def test_conflict_working_on_overlap(self):
        # Another agent claims the same file
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_STATUS, agent_id="other", working_on=["src/app.ts"]
                ),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_conflict_stale_question(self):
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        self._write_events([q, *filler])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(any("stale" in c["content"].lower() for c in concerns))

    def test_conflict_superseded_decision(self):
        self._write_events(
            [
                make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres"),
                make_event(EVENT_TYPE_DECISION, topic="db", content="Use MySQL"),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(any("superseded" in c["content"].lower() for c in concerns))

    def test_conflict_assumption_contradicted(self):
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        self._write_events([a, d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_conflict_convention_violation(self):
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONVENTION, topic="naming", content="Use camelCase"
                ),
                make_event(
                    EVENT_TYPE_DECISION, topic="naming", content="Use snake_case"
                ),
            ]
        )
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(any("convention" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [
                make_event(EVENT_TYPE_STATUS, agent_id="main", working_on=["src/a.ts"]),
                make_event(EVENT_TYPE_DECISION, topic="db", content="Use Postgres"),
            ]
        )
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/b.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0)

    def test_semantic_references(self):
        # Decision references our file
        d = make_event(
            EVENT_TYPE_DECISION,
            topic="auth",
            content="Use JWT",
            working_on=["src/auth.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/auth.ts", "content": "x"}),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertTrue(len(statuses) >= 1)
        refs = statuses[0].get("references", [])
        self.assertIn(d["id"], refs)

    def test_no_semantic_refs_unrelated(self):
        d = make_event(
            EVENT_TYPE_DECISION,
            topic="auth",
            content="Use JWT",
            working_on=["src/other.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
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
from event_schema import EVENT_TYPE_CONCERN  # noqa: E402


class TestPostToolExitPlan(_HookTestCase):
    """PostToolUse:ExitPlanMode writes marker, event, and returns context."""

    def test_returns_review_nudge(self):
        """Should return additionalContext nudging /xp-review-plan."""
        result = post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
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
        """Should append plan_awaiting_review event tagged with plan_exited action."""
        from event_schema import STATUS_ACTION_PLAN_EXITED

        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)
        metadata = gate[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_PLAN_EXITED)

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


import bash_post_tool  # noqa: E402
import tdd_check  # noqa: E402
from _commit_helpers import patch_commits  # noqa: E402
from concerns import TEST_FAILURES_PREFIX  # noqa: E402
from conftest import _make_bash_input  # noqa: E402


class TestCapturedRunnerStatusEmission(_HookTestCase):
    """The SECOND way a green run un-gates a red one: the STATUS event itself.

    Resolving concerns is not the only leg. `tdd_check.find_last_test_signal`
    walks the log backwards and returns "pass" the moment it meets a status
    matching its pass pattern — short-circuiting before it ever reaches the
    open failure concern, with no resolution event anywhere. That append sits
    in the is-a-test-run branch, OUTSIDE the clear branch's guard, so gating
    only the clear leaves a PASS-shaped digest to un-gate the suite anyway.

    `pytest | tee out.log` is the shape that makes this concrete rather than
    hypothetical: the pipe hands tee the runner's output verbatim (so the
    counts really do parse as green) while handing the shell only TEE's exit
    status — the runner may have been red the whole time.
    """

    CAPTURED = "python3 -m pytest tests/ | tee out.log"
    GREEN_OUTPUT = "5 passed in 1.20s"

    def _statuses(self) -> list[dict]:
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return events_of_type(events, EVENT_TYPE_STATUS)

    def _run(self, command: str, stdout: str) -> str | None:
        with patch_commits(files=[], body=""):
            return bash_post_tool.run(
                _make_bash_input(command=command, stdout=stdout),
                smm_dir=self.smm_dir,
            )

    def _open_failure(self) -> None:
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_CONCERN,
                content=f"{TEST_FAILURES_PREFIX}: 3 failed (pytest)",
                severity="high",
            ),
        )

    def test_captured_runner_emits_no_pass_shaped_status(self):
        """The digest must not read as a pass the gate would trust."""
        self._run(self.CAPTURED, self.GREEN_OUTPUT)
        statuses = self._statuses()
        self.assertEqual(len(statuses), 1, "the run is still recorded, just honestly")
        self.assertIsNone(
            tdd_check.TEST_PASS_RE.search(statuses[0]["content"]),
            f"un-gating status content: {statuses[0]['content']!r}",
        )

    def test_captured_runner_does_not_un_gate_tdd_check(self):
        """End to end through the consumer that the shape actually fools."""
        self._open_failure()
        self._run(self.CAPTURED, self.GREEN_OUTPUT)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(tdd_check.find_last_test_signal(events), "fail")

    def test_uncaptured_green_run_still_emits_a_pass(self):
        """Anti-deadlock control: the honest green path is untouched, or
        nothing would ever un-gate a red run again."""
        self._open_failure()
        self._run("python3 -m pytest tests/", self.GREEN_OUTPUT)
        statuses = self._statuses()
        self.assertIsNotNone(tdd_check.TEST_PASS_RE.search(statuses[0]["content"]))

    def test_refusal_is_explained_and_names_capture(self):
        """A silent refusal is an armed gate with no way out: the agent sees
        no reason and no hint that a plain re-run clears it. The reason must
        point at the captured exit status, not at being compound — plenty of
        compounds still clear."""
        advisory = self._run(self.CAPTURED, self.GREEN_OUTPUT)
        advisory = self._assert_not_none(advisory)
        self.assertIn("exit status", advisory.lower())
        self.assertNotIn("compound", advisory.lower())

    def test_live_evidence_does_not_report_failures_resolved(self):
        """AC #5, verbatim: the command that announced a red suite green.

        `OUT=$(pytest ...)` captures the runner's exit into a string and
        `echo $?` reports the SUBSTITUTION's status, so the shell sees 0 over
        a suite that exited 1.

        The gate assertion carries the weight here. Suppressing the message
        alone would be cosmetic — the disarm is the resolution event it
        announces, and `find_last_test_signal` is what the stop gate reads.
        """
        self._open_failure()
        advisory = self._run("OUT=$(python3 -m pytest tests/); echo $?", "1\n")
        self.assertNotIn("All prior test failures resolved", advisory or "")
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(tdd_check.find_last_test_signal(events), "fail")


if __name__ == "__main__":
    unittest.main()
