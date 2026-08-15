#!/usr/bin/env python3
"""Tests for the review_cycle_done PostToolUse:Skill|Agent hook.

Split from test_review_cycle.py by test-class grouping: this file covers
review_cycle_done.py — the review-skill/agent-completion routing
(TestReviewCycleDone), the target allowlist (TestDetectTargetAllowlist),
and agent_id/metadata.action semantics (TestAgentIdSemantics). See
test_review_cycle_subagent_stop.py for the SubagentStop backup-detection
siblings (subagent_stop.py).
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import review_cycle_done
import review_records
from conftest import _HookTestCase, _make_agent_input, _make_skill_input
from event_schema import EVENT_TYPE_STATUS, event_action

_WATERMARK_ID = "test-review-cycle"


class TestReviewCycleDone(_HookTestCase):
    """PostToolUse:Skill|Agent hook sets flags after review skills or xp-housekeeper."""

    def test_code_review_sets_flag(self):
        review_cycle_done.run(_make_skill_input("code-review"), smm_dir=self.smm_dir)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_legacy_simplify_no_longer_sets_flag(self):
        """Cutover: the renamed-away /simplify name is inert — only /code-review
        clears the gate now."""
        review_cycle_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_quality_review_skill_is_inert(self):
        """An INLINE skill's Skill TOOL call returns — and fires this hook — at LAUNCH.

        The skill has not reviewed anything yet at that moment: it has not
        run its own Step 1. Setting the flag there let an invoked-and-
        abandoned skill clear the commit gate, and let a commit landing
        DURING the review clear the flag with nothing left to set it again
        at completion. The reviewer's completion carries it instead.
        """
        result = review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        self.assertIsNone(result)

    def test_code_reviewer_completion_sets_quality_flag(self):
        """The reviewer subagent returning IS the review completing.

        One spawn per cycle (the skill's single-spawn invariant), so this
        fires exactly once per review.
        """
        review_cycle_done.run(
            _make_agent_input("xp-agents:xp-code-reviewer", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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

    def test_code_reviewer_completion_emits_action_event(self):
        """action=qr_complete rides the reviewer's completion, not the launch.

        `commit_event` reads this event as a second, independent "was there
        a review since the last commit" advisory. Emitted at launch, the
        skill satisfied that advisory by being invoked.
        """
        review_cycle_done.run(
            _make_agent_input("xp-agents:xp-code-reviewer", agent_type=""),
            smm_dir=self.smm_dir,
        )
        emitted = self._action_events("qr_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], EVENT_TYPE_STATUS)

    def test_quality_review_skill_emits_no_action_event(self):
        """The launch must claim nothing — "Quality review complete" at launch
        is a false record, not merely an early one."""
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        self.assertEqual(len(self._action_events("qr_complete")), 0)

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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        emitted = self._action_events("simplify_complete")
        self.assertEqual(len(emitted), 0)

    def test_xp_code_reviewer_completion_sets_neither_simplify_flag(self):
        """Collision guard: the reviewer carries the QUALITY flag, never SIMPLIFY.

        Its completion arrives as PostToolUse in the MAIN agent's context
        (invoking agent_type is non-xp; tool_input.subagent_type is the
        reviewer), so the is_xp_agent skip — which checks the invoking agent,
        NOT subagent_type — does not fire here. The reviewer's name contains
        the `code-review` substring, so routing it to SIMPLIFY would clear the
        half of the cycle that belongs to /code-review, which may never have run.
        """
        input_data = _make_agent_input("xp-agents:xp-code-reviewer", agent_type="")
        review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_ignores_other_skills(self):
        review_cycle_done.run(_make_skill_input("xp-kickoff"), smm_dir=self.smm_dir)
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "worktree-story-001")
        self.assertTrue(cycle["simplify_done"])
        main_cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        ("xp-code-reviewer", review_cycle_done._TARGET_QUALITY_REVIEW),
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

    def test_xp_code_reviewer_routes_to_quality_not_simplify(self):
        """xp-code-reviewer (contains the 'code-review' substring) carries the
        QUALITY target. The exact-match allowlist is what keeps the substring
        from routing it to SIMPLIFY."""
        for name in ("xp-code-reviewer", "xp-agents:xp-code-reviewer"):
            with self.subTest(name=name):
                self.assertEqual(
                    review_cycle_done._detect_target(name),
                    review_cycle_done._TARGET_QUALITY_REVIEW,
                )

    def test_quality_review_skill_routes_to_none(self):
        """The SKILL name is off the allowlist: its PostToolUse fires at launch,
        so it must route nowhere. Only the reviewer's completion counts."""
        self.assertIsNone(review_cycle_done._detect_target("xp-quality-review"))
        self.assertIsNone(
            review_cycle_done._detect_target("xp-agents:xp-quality-review")
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


class TestSpawnedReviewerNameIsTheRoutedName(unittest.TestCase):
    """Both sides of the contract the quality flag now rides on.

    The flag is set by the AGENT the skill spawns, so the `subagent_type`
    /xp-quality-review passes must be a name `_detect_target` routes to the
    quality target. Renaming either half alone leaves the commit gate with
    nothing to clear it, and the skill's own prose pin (which only looks for
    the substring anywhere in the body) would still pass.
    """

    _SKILL_MD = (
        Path(__file__).parent.parent.parent
        / "skills"
        / "xp-quality-review"
        / "SKILL.md"
    )

    def test_skill_spawns_a_subagent_type_routing_to_quality_target(self):
        """At LEAST one spawned name, not every one: a future second spawn (a
        helper agent) routing elsewhere is legitimate, while a rename of the
        reviewer is still red."""
        spawned = re.findall(r'subagent_type:\s*"([^"]+)"', self._SKILL_MD.read_text())
        self.assertTrue(spawned, "SKILL.md must declare a subagent_type to spawn")
        routed = {n: review_cycle_done._detect_target(n) for n in spawned}
        self.assertIn(
            review_cycle_done._TARGET_QUALITY_REVIEW, routed.values(), str(routed)
        )


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
            _make_agent_input(
                "xp-agents:xp-code-reviewer", agent_type="", agent_id="teammate-9"
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        emitted = [e for e in events if event_action(e) == "qr_complete"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "teammate-9")


if __name__ == "__main__":
    unittest.main()
