#!/usr/bin/env python3
"""Tests for review cycle hooks: review_cycle_done and subagent review flags.

Split from test_subagent.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import review_cycle_done
import subagent_stop
from conftest import _HookTestCase, _make_agent_input, _make_skill_input
from event_schema import EVENT_TYPE_STATUS, event_action

_WATERMARK_ID = "test-review-cycle"


class TestReviewCycleDone(_HookTestCase):
    """PostToolUse:Skill|Agent hook sets flags after review skills or xp-housekeeper."""

    def test_code_review_sets_flag(self):
        review_cycle_done.run(_make_skill_input("code-review"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_legacy_simplify_no_longer_sets_flag(self):
        """Cutover: the renamed-away /simplify name is inert — only /code-review
        clears the gate now."""
        review_cycle_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_quality_review_sets_flag(self):
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def _action_events(self, action: str) -> list[dict]:
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return [e for e in events if event_action(e) == action]

    def test_code_review_emits_action_event(self):
        """/code-review completion appends a status event with the (internally
        unchanged) action=simplify_complete."""
        review_cycle_done.run(_make_skill_input("code-review"), smm_dir=self.smm_dir)
        emitted = self._action_events("simplify_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], EVENT_TYPE_STATUS)

    def test_quality_review_emits_action_event(self):
        """/xp-quality-review completion appends action=qr_complete."""
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        emitted = self._action_events("qr_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], EVENT_TYPE_STATUS)

    def test_security_review_emits_action_event(self):
        """/security-review records exactly one event with action=security_complete."""
        review_cycle_done.run(
            _make_skill_input("security-review"), smm_dir=self.smm_dir
        )
        emitted = self._action_events("security_complete")
        self.assertEqual(len(emitted), 1)
        # agent_id is attribution (teammate-resolved); skill identity lives
        # in metadata.action. _make_skill_input defaults agent_id to "main".
        self.assertEqual(emitted[0]["agent_id"], "main")

    def test_security_review_returns_continuation_nudge(self):
        """/security-review completion returns continuation context so orchestrated
        callers (close-skill Step 4.5 gate) can proceed past the skill's
        'reply with markdown report only' stop-instruction.
        """
        result = review_cycle_done.run(
            _make_skill_input("security-review"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("orchestrated", result.lower())

    def test_security_review_for_xp_agent_emits_event_and_returns_nudge(self):
        """xp-* subagents invoking /security-review MUST receive both the
        SECURITY_COMPLETE event and the continuation nudge — the
        recursion-prevention skip excludes /security-review because the
        orchestrated close-skill flow needs both signals to proceed.
        """
        input_data = _make_skill_input(
            "security-review", agent_type="xp-close-reviewer"
        )
        result = review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        assert result is not None
        self.assertIn("orchestrated", result.lower())
        emitted = self._action_events("security_complete")
        self.assertEqual(len(emitted), 1)

    def test_xp_agent_skips_code_review(self):
        """The recursion-prevention skip remains in effect for /code-review
        invocations from xp-* subagents — only /security-review is excepted.
        """
        input_data = _make_skill_input("code-review", agent_type="xp-test")
        result = review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        emitted = self._action_events("simplify_complete")
        self.assertEqual(len(emitted), 0)

    def test_xp_code_reviewer_completion_does_not_set_flag(self):
        """Collision guard: when /xp-quality-review spawns the xp-code-reviewer
        agent, its completion arrives as PostToolUse in the MAIN agent's context
        (invoking agent_type is non-xp; tool_input.subagent_type is the reviewer).
        The is_xp_agent skip checks the invoking agent, NOT subagent_type — so it
        does not fire here. _detect_target must itself exclude the reviewer, or it
        falsely clears the commit gate before /code-review ever ran."""
        input_data = _make_agent_input("xp-agents:xp-code-reviewer", agent_type="")
        review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertEqual(len(self._action_events("simplify_complete")), 0)

    def test_plan_review_emits_action_event(self):
        """/xp-review-plan completion appends action=plan_reviewed."""
        review_cycle_done.run(_make_skill_input("xp-review-plan"), smm_dir=self.smm_dir)
        emitted = self._action_events("plan_reviewed")
        self.assertEqual(len(emitted), 1)

    def test_housekeeping_emits_action_event(self):
        """xp-housekeeper agent completion appends action=housekeeping_complete."""
        review_cycle_done.run(_make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir)
        emitted = self._action_events("housekeeping_complete")
        self.assertEqual(len(emitted), 1)

    def test_qualified_code_review_name(self):
        """Prefixed skill names also match (substring detection tolerates a prefix)."""
        review_cycle_done.run(
            _make_skill_input("xp-agents:code-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_ignores_other_skills(self):
        review_cycle_done.run(_make_skill_input("xp-kickoff"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_code_review_nudges_quality_review(self):
        """After /code-review, nudge to run /xp-quality-review."""
        result = review_cycle_done.run(
            _make_skill_input("code-review"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_plan_review_does_not_nudge_task_creation(self):
        """/xp-review-plan returns no additionalContext — execution mode isn't
        decided yet at plan-review time, so the nudge fires at /xp-assign
        where mode is known. Asserting None (not just 'no TaskCreate text')
        catches future regressions that would re-introduce a different
        plan-review nudge."""
        result = review_cycle_done.run(
            _make_skill_input("xp-review-plan"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_plan_review_does_not_set_review_flags(self):
        """Plan review is not part of the commit review cycle."""
        review_cycle_done.run(_make_skill_input("xp-review-plan"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_assign_nudge_covers_taskcreate_solo_and_teammates(self):
        """Teammate-mode nudge after /xp-assign: must mention TaskCreate AND
        the per-story coordination tasks (plan next story, wait+accept on
        this teammate). /xp-assign is teammate-only — /xp-schedule branches
        solo directly — so the nudge no longer needs to address solo mode."""
        result = review_cycle_done.run(
            _make_skill_input("xp-assign"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("TaskCreate", result)
        lower = result.lower()
        self.assertIn("teammate", lower)
        self.assertIn("/xp-accept", result)

    def test_assign_emits_action_event(self):
        """/xp-assign completion appends action=assign_complete so consumers
        (retro_metrics, analyzers) can detect the lifecycle event without
        regex-matching content."""
        review_cycle_done.run(_make_skill_input("xp-assign"), smm_dir=self.smm_dir)
        emitted = self._action_events("assign_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], EVENT_TYPE_STATUS)

    def test_assign_does_not_set_review_flags(self):
        """Assign is not part of the commit review cycle."""
        review_cycle_done.run(_make_skill_input("xp-assign"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_qualified_assign_name(self):
        """Plugin-qualified xp-agents:xp-assign also triggers the nudge."""
        result = review_cycle_done.run(
            _make_skill_input("xp-agents:xp-assign"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("TaskCreate", result)

    def test_housekeeper_agent_returns_process_guide(self):
        """After xp-housekeeper Agent call, inject PROCESS_GUIDE.md as context."""
        result = review_cycle_done.run(
            _make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("Practicing the Values", result)

    def test_housekeeper_qualified_name(self):
        """Plugin-qualified xp-agents:xp-housekeeper also triggers process guide."""
        result = review_cycle_done.run(
            _make_agent_input("xp-agents:xp-housekeeper"), smm_dir=self.smm_dir
        )
        assert result is not None
        self.assertIn("Practicing the Values", result)

    def test_housekeeper_does_not_set_review_flags(self):
        """Housekeeper is not part of the commit review cycle."""
        review_cycle_done.run(_make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_worktree_cwd_scopes_markers(self):
        """Worktree cwd uses resolve_agent_id for marker scoping."""
        inp = _make_skill_input(
            "code-review",
            agent_id="",
            cwd="/proj/.claude/worktrees/worktree-story-001",
        )
        review_cycle_done.run(inp, smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "worktree-story-001")
        self.assertTrue(cycle["simplify_done"])
        main_cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(main_cycle.get("simplify_done", False))


class TestDetectTargetAllowlist(unittest.TestCase):
    """story-006: _detect_target uses an explicit allowlist (no substring matching).

    Closes the false-positive class where a future skill like
    `xp-quality-reviewer-helper` would route to `_TARGET_QUALITY_REVIEW`
    under the old substring chain. Mirrors the precedent in
    `accept_terminal._is_terminal_target` (sprint-104 commit 1173083f).
    """

    _KNOWN_TARGETS = (
        ("code-review", review_cycle_done._TARGET_SIMPLIFY),
        ("xp-quality-review", review_cycle_done._TARGET_QUALITY_REVIEW),
        ("security-review", review_cycle_done._TARGET_SECURITY_REVIEW),
        ("xp-review-plan", review_cycle_done._TARGET_PLAN_REVIEW),
        ("xp-assign", review_cycle_done._TARGET_ASSIGN),
        ("xp-housekeeper", review_cycle_done._TARGET_HOUSEKEEPING),
    )

    def test_each_known_target_routes(self):
        for name, expected in self._KNOWN_TARGETS:
            with self.subTest(name=name):
                self.assertEqual(review_cycle_done._detect_target(name), expected)

    def test_each_qualified_name_routes(self):
        """Plugin-qualified form `xp-agents:<bare>` resolves to the same target."""
        for bare, expected in self._KNOWN_TARGETS:
            # Built-ins (code-review, security-review) can also be qualified
            # by the harness; cover them in the same loop.
            qualified = f"xp-agents:{bare}"
            with self.subTest(name=qualified):
                self.assertEqual(review_cycle_done._detect_target(qualified), expected)

    def test_xp_code_reviewer_routes_to_none(self):
        """AC #1: xp-code-reviewer (contains 'code-review' substring) must
        NOT route to SIMPLIFY — the allowlist excludes it by construction."""
        self.assertIsNone(review_cycle_done._detect_target("xp-code-reviewer"))
        self.assertIsNone(
            review_cycle_done._detect_target("xp-agents:xp-code-reviewer")
        )

    def test_unknown_helper_names_route_to_none(self):
        """AC #2: hypothetical helper-suffix names (which the substring chain
        would have matched) must return None under the allowlist."""
        false_positives = [
            "xp-quality-reviewer-helper",  # substring code returns QUALITY_REVIEW
            "xp-housekeeper-helper",  # substring code returns HOUSEKEEPING
            # Belt-and-braces: these don't match either path, but pin the
            # closed-set guarantee.
            "xp-assignment",
            "xp-review-plan-tool",
        ]
        for name in false_positives:
            with self.subTest(name=name):
                self.assertIsNone(review_cycle_done._detect_target(name))

    def test_empty_target_returns_none(self):
        """Empty input is benign — already returned None implicitly; pin it."""
        self.assertIsNone(review_cycle_done._detect_target(""))

    def test_other_plugin_qualified_name_routes_to_none(self):
        """sprint-close finding A6: only the 'xp-agents:' namespace is ours.
        A third-party plugin's '/otherplugin:code-review' would otherwise
        falsely set simplify_done via the bare-form fallback."""
        for entry in self._KNOWN_TARGETS:
            qualified = f"otherplugin:{entry[0]}"
            with self.subTest(name=qualified):
                self.assertIsNone(review_cycle_done._detect_target(qualified))
        # Also pin the empty/malformed namespace case.
        self.assertIsNone(review_cycle_done._detect_target(":code-review"))


class TestAgentIdSemantics(_HookTestCase):
    """agent_id is teammate attribution; metadata.action carries skill identity.

    review_cycle_done previously emitted lifecycle events with agent_id set
    to a skill-name string (e.g. "xp-quality-review"), drawn from a third
    tuple element in _TARGET_LIFECYCLE. Per the agent-id-semantics ADR
    (sprint-042), every hook producer writes the resolved teammate agent_id;
    skill identity lives in metadata.action.
    """

    def test_code_review_event_uses_resolved_agent_id(self):
        review_cycle_done.run(
            _make_skill_input("code-review", agent_id="teammate-7"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        emitted = [e for e in events if event_action(e) == "simplify_complete"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "teammate-7")

    def test_quality_review_event_uses_resolved_agent_id(self):
        review_cycle_done.run(
            _make_skill_input("xp-quality-review", agent_id="teammate-9"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        emitted = [e for e in events if event_action(e) == "qr_complete"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "teammate-9")


class TestSubagentStopReviewFlags(_HookTestCase):
    """SubagentStop backup: detect review-related subagent completions."""

    def _stop_input(self, agent_id: str, agent_type: str = "", **overrides) -> dict:
        data = {
            "session_id": "t",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": "Done",
        }
        data.update(overrides)
        return data

    def test_code_review_agent_type_sets_flag(self):
        """SubagentStop with agent_type containing 'code-review' sets flag."""
        subagent_stop.run(
            self._stop_input("task-1", agent_type="code-review"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_quality_review_agent_type_sets_flag(self):
        """SubagentStop with agent_type 'xp-quality-review' sets flag."""
        subagent_stop.run(
            self._stop_input("task-2", agent_type="xp-quality-review"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_code_review_agent_id_sets_flag(self):
        """SubagentStop with agent_id containing 'code-review' sets flag."""
        subagent_stop.run(
            self._stop_input("code-review-reuse-1", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_other_plugin_qualified_code_review_does_not_set_flag(self):
        """sprint-close finding A6 (subagent_stop leg): a third-party plugin's
        completion (e.g. 'otherplugin:code-review' as agent_type) must NOT
        clear our simplify_done flag. The substring _is_code_review currently
        matches; tighten by scoping the qualified form to our namespace."""
        subagent_stop.run(
            self._stop_input("o-1", agent_type="otherplugin:code-review"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_xp_code_reviewer_agent_does_not_set_flag(self):
        """Collision guard: our own xp-code-reviewer agent (spawned by
        /xp-quality-review) contains the substring 'code-review' but must NOT
        set the simplify flag. _update_review_cycle_flags runs before the
        is_xp_agent skip, so the guard ('code-reviewer' not in name) is what
        prevents the false positive."""
        subagent_stop.run(
            self._stop_input("rev-1", agent_type="xp-code-reviewer"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_qualified_xp_code_reviewer_does_not_set_flag(self):
        """Plugin-qualified xp-agents:xp-code-reviewer is also excluded."""
        subagent_stop.run(
            self._stop_input("rev-2", agent_type="xp-agents:xp-code-reviewer"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_xp_quality_review_helper_does_not_set_flag(self):
        """sprint-close finding A5: the symmetric guard 'quality-reviewer not in'
        only excludes the 'er'-spelling. A helper agent named
        'xp-quality-review-helper' (no 'er') would still flip the flag —
        exactly the defect class story-006 was meant to close. Exact-match
        allowlist closes both spellings."""
        subagent_stop.run(
            self._stop_input("h-1", agent_type="xp-quality-review-helper"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])

    def test_xp_quality_reviewer_helper_does_not_set_flag(self):
        """story-006 symmetric guard: a future name like 'xp-quality-reviewer-helper'
        contains the substring 'quality-review' but must NOT set the
        quality_review_done flag. Mirrors `_is_code_review`'s 'code-reviewer not in'
        exclusion. Closes the parallel defect class in `_update_review_cycle_flags`
        (debt b2389e3f725d)."""
        subagent_stop.run(
            self._stop_input("helper-1", agent_type="xp-quality-reviewer-helper"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        # Same guard must hold for agent_id-driven matches.
        subagent_stop.run(
            self._stop_input("xp-quality-reviewer-helper-9", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])

    def test_legacy_simplify_agent_type_no_longer_sets_flag(self):
        """Cutover: a subagent named 'simplify' no longer sets the flag."""
        subagent_stop.run(
            self._stop_input("task-9", agent_type="simplify"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_regular_subagent_no_flag(self):
        """Regular subagent does not set any review flags."""
        subagent_stop.run(
            self._stop_input("task-3", agent_type="task"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_plan_subagent_no_review_flag(self):
        """Plan subagent writes plan marker but not review flags."""
        subagent_stop.run(
            self._stop_input("plan-1", agent_type="Plan"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_worktree_cwd_scopes_review_flag(self):
        """SubagentStop in a teammate worktree scopes the flag to that
        teammate, not 'main'."""
        subagent_stop.run(
            self._stop_input(
                "task-1",
                agent_type="code-review",
                cwd="/proj/.claude/worktrees/worktree-story-001",
            ),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "worktree-story-001")
        self.assertTrue(cycle["simplify_done"])

    def test_null_cwd_does_not_raise_and_falls_back_to_main(self):
        """An explicit `"cwd": null` SubagentStop payload must not raise
        (.get('cwd', '') returns None, not ''); the flag falls back to
        'main' so the hook still records and arms the review flag."""
        subagent_stop.run(
            self._stop_input("task-1", agent_type="code-review", cwd=None),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])


class TestPlanReviewerSetsAssignPending(_HookTestCase):
    """SubagentStop for xp-plan-reviewer sets .assign-pending — but only in
    teammate mode (the planned in-progress story is execution_mode=='teammate').
    """

    def _stop_input(self, agent_id: str, agent_type: str = "") -> dict:
        return {
            "session_id": "t",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": "Review complete",
        }

    def _write_teammate_sprint(self):
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "t", "in-progress", execution_mode="teammate")]
            )
        )

    def test_plan_reviewer_sets_assign_marker(self):
        """Teammate-mode xp-plan-reviewer completion creates .assign-pending."""
        self._write_teammate_sprint()
        subagent_stop.run(
            self._stop_input("review-1", agent_type="xp-plan-reviewer"),
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".assign-pending"
        self.assertTrue(marker.exists(), "assign-pending marker not created")

    def test_plan_reviewer_returns_none(self):
        """Teammate-mode xp-plan-reviewer completion returns no continuing
        context (debt 5e180220db1a). SubagentStop additionalContext is routed
        back to the finished reviewer, where a nudge buried its Final Message;
        the gate is the .assign-pending marker + plan_reviewed event instead."""
        self._write_teammate_sprint()
        result = subagent_stop.run(
            self._stop_input("review-1", agent_type="xp-plan-reviewer"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_non_reviewer_no_assign_marker(self):
        """Other xp-* agents don't set assign-pending marker."""
        subagent_stop.run(
            self._stop_input("retro-1", agent_type="xp-retrospective"),
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".assign-pending"
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
