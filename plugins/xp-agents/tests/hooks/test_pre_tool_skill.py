#!/usr/bin/env python3
"""Tests for PreToolUse:Skill hook — code-review nudge + teammate gate."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import pre_tool_skill
from conftest import (
    SPRINT_CLOSING_ONLY,
    SPRINT_REVIEWING_ONLY,
    _HookTestCase,
    _make_skill_input,
)

# A CLI teammate's cwd sits inside a `worktree-story-` worktree; an in-place
# teammate's cwd is the main checkout, detected instead by XP_TEAMMATE_NAME.
_TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"


class TestCodeReviewNudge(_HookTestCase):
    """PreToolUse:Skill injects courage nudge before /code-review."""

    def test_code_review_gets_courage_nudge(self):
        """When /code-review runs, inject courage + identify-only reminder."""
        result = pre_tool_skill.run(_make_skill_input("code-review"))
        result = self._assert_not_none(result)
        self.assertIn("Courage", result)
        # /code-review is identify-only now; the fix happens in quality-review.
        self.assertIn("/xp-quality-review", result)
        # The old "code reuse agent" no longer exists — don't resurrect it.
        self.assertNotIn("code reuse agent", result)

    def test_code_review_plugin_prefixed(self):
        """Prefixed code-review also gets nudge."""
        result = pre_tool_skill.run(_make_skill_input("xp-agents:code-review"))
        result = self._assert_not_none(result)
        self.assertIn("Courage", result)

    def test_unrelated_skills_no_output(self):
        """Skills that are not code-review get nothing."""
        result = pre_tool_skill.run(_make_skill_input("xp-sprint-start"))
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """xp-* agents skip the nudge."""
        result = pre_tool_skill.run(
            _make_skill_input("code-review", agent_type="xp-retrospective")
        )
        self.assertIsNone(result)

    def test_courage_nudge_names_workflow_tool_not_skill(self):
        """story-011: /code-review runs via the Workflow tool, not Skill.
        Even though this branch is provably unreachable in practice
        (code-review is absent from the Skill listing, so the model can't
        dispatch Skill(code-review) in the first place — see discovery
        6e088a55f0dc), the message should redirect to the Workflow tool
        rather than staying silent on how to actually launch it."""
        result = pre_tool_skill.run(_make_skill_input("code-review"))
        result = self._assert_not_none(result)
        self.assertIn("Workflow", result)
        self.assertIn("Skill", result)

    def test_courage_nudge_does_not_imply_per_commit_cadence(self):
        """/code-review runs once at sprint/plan/free-close, never per commit
        (per-commit is /xp-quality-review only), so the nudge must not tell
        the agent to run it on every change."""
        result = pre_tool_skill.run(_make_skill_input("code-review"))
        result = self._assert_not_none(result)
        self.assertNotIn("every change", result)
        self.assertNotIn("every commit", result)


class TestTeammateLifecycleGate(_HookTestCase):
    """PreToolUse:Skill blocks teammates from lead-owned lifecycle skills."""

    def test_teammate_blocked_from_accept(self):
        """A worktree teammate invoking /xp-accept is blocked."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-accept", cwd=_TEAMMATE_CWD)
        )
        reason = self._assert_not_none(reason)
        self.assertIn("lead", reason.lower())

    def test_teammate_blocked_from_story_close(self):
        """A worktree teammate invoking /xp-story-close is blocked."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-story-close", cwd=_TEAMMATE_CWD)
        )
        self._assert_not_none(reason)

    def test_in_place_teammate_blocked_via_env(self):
        """A GENUINE in-place teammate (env name + live in-place marker, no
        worktree cwd) is detected and blocked. This is the legacy2 sprint-014
        failure: an in-place solo teammate ran its own /xp-story-close.
        """
        import worktree

        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-008")
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-008"}):
            reason = pre_tool_skill.teammate_block_reason(
                _make_skill_input("xp-sprint-close", cwd="/home/user/project"),
                smm_dir=self.smm_dir,
            )
        self._assert_not_none(reason)

    def test_leaked_env_lead_not_blocked(self):
        """A lead with a LEAKED XP_TEAMMATE_NAME but NO live in-place marker is
        NOT a teammate — it must not be locked out of lead-owned skills. Mirrors
        commit_handling's marker guard so the two legs of the leak defense agree.
        """
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-008"}):
            reason = pre_tool_skill.teammate_block_reason(
                _make_skill_input("xp-accept", cwd="/home/user/project"),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(reason)

    def test_teammate_blocked_namespaced(self):
        """Our-namespace-qualified lead skill is blocked for teammates."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-agents:xp-plan-close", cwd=_TEAMMATE_CWD)
        )
        self._assert_not_none(reason)

    def test_teammate_allowed_quality_review(self):
        """The review cycle is the one xp skill a teammate may run."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-quality-review", cwd=_TEAMMATE_CWD)
        )
        self.assertIsNone(reason)

    def test_teammate_allowed_code_review(self):
        """Built-in /code-review (not ours) passes through — not a lifecycle skill."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("code-review", cwd=_TEAMMATE_CWD)
        )
        self.assertIsNone(reason)

    def test_teammate_third_party_passes(self):
        """A third-party plugin skill is never our concern."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("otherplugin:xp-accept", cwd=_TEAMMATE_CWD)
        )
        self.assertIsNone(reason)

    def test_lead_not_blocked(self):
        """The lead (not a teammate) runs lead-owned skills freely."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-accept", cwd="/home/user/project")
        )
        self.assertIsNone(reason)

    def test_xp_subagent_skips(self):
        """Our own xp- subagents are exempt (recursion guard)."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input(
                "xp-accept", cwd=_TEAMMATE_CWD, agent_type="xp-code-reviewer"
            )
        )
        self.assertIsNone(reason)

    def test_our_skills_matches_shipped_dir(self):
        """Superset guard: _OUR_SKILLS is pinned to the shipped skills/ dir.

        A new skill fails this until it is classified — lead-owned (blocked by
        default) or added to the teammate allowlist — so the gate can't silently
        skip it. Mirrors the classifier-SIGNALS superset guard.
        """
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        shipped = {
            p.name
            for p in skills_dir.iterdir()
            if p.is_dir() and p.name.startswith("xp-")
        }
        self.assertEqual(pre_tool_skill._OUR_SKILLS, shipped)
        # The allowlist must be a subset of our skills (no stray names).
        self.assertTrue(
            pre_tool_skill._TEAMMATE_ALLOWED_SKILLS <= pre_tool_skill._OUR_SKILLS
        )


class TestAcceptEvidenceGate(_HookTestCase):
    """PreToolUse:Skill blocks a lead from /xp-story-close without accept evidence."""

    _LEAD_CWD = "/home/user/project"

    def test_lead_blocked_from_story_close_without_closing_story(self):
        """No story in `closing` -> direct /xp-story-close is refused."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self._assert_not_none(reason)

    def test_lead_allowed_story_close_with_closing_story(self):
        """A story in `closing` (accept-driven) -> not blocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_ONLY)
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(reason)

    def test_accept_in_flight_without_closing_story_still_blocked(self):
        """ACCEPT_IN_FLIGHT is a session signal, not per-story evidence: armed but
        with NO closing story -> STILL blocked (regression against the old code)."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self._assert_not_none(reason)

    def test_missing_sprint_blocks(self):
        """No sprint.json -> no closing story -> block (no legit close exists)."""
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self._assert_not_none(reason)

    def test_corrupt_sprint_blocks(self):
        """Fail CLOSED: an unparseable sprint.json must block, never allow."""
        (self.smm_dir / "sprint.json").write_text("{ not valid json")
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self._assert_not_none(reason)

    def test_teammate_still_blocked_from_story_close(self):
        """Teammate precedence still applies (AC #3) — no regression."""
        reason = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-story-close", cwd=_TEAMMATE_CWD)
        )
        self._assert_not_none(reason)

    def test_other_close_skills_not_gated_by_accept_evidence(self):
        """Only xp-story-close is gated — sprint/plan/free close pass through."""
        for skill in ("xp-sprint-close", "xp-plan-close", "xp-free-close"):
            reason = pre_tool_skill.accept_evidence_block_reason(
                _make_skill_input(skill, cwd=self._LEAD_CWD),
                smm_dir=self.smm_dir,
            )
            self.assertIsNone(reason, f"{skill} should not be gated")

    def test_missing_smm_dir_does_not_block(self):
        """Degrade quiet: an unresolvable SMM dir must never block a legit close."""
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=Path("/nonexistent/smm/dir"),
        )
        self.assertIsNone(reason)

    def test_xp_subagent_skips_accept_evidence_gate(self):
        """Recursion guard: our own xp- subagents are exempt."""
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input(
                "xp-story-close", cwd=self._LEAD_CWD, agent_type="xp-code-reviewer"
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(reason)

    def test_lead_passes_teammate_gate_then_blocked_by_accept_gate(self):
        """Composition (AC #3 precedence): a lead's direct /xp-story-close is
        allowed by the teammate gate (not a teammate) but refused by the accept
        gate (no evidence). Asserts the two helpers in isolation; the __main__
        dispatch that chains them is proven end-to-end by the subprocess test in
        tests/integration/test_gate_enforcement.py.
        """
        block = pre_tool_skill.teammate_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(block)
        reason = pre_tool_skill.accept_evidence_block_reason(
            _make_skill_input("xp-story-close", cwd=self._LEAD_CWD),
            smm_dir=self.smm_dir,
        )
        self._assert_not_none(reason)


if __name__ == "__main__":
    unittest.main()
