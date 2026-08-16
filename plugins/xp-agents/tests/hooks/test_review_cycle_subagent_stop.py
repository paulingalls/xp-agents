#!/usr/bin/env python3
"""Tests for the SubagentStop review-flag legs and their allowlist guards.

Split from test_review_cycle.py by test-class grouping: this file covers
subagent_stop.py's review-related SubagentStop handling — the name matching
in `review_cycle_legs` that decides which completion means which flag
(TestSubagentStopReviewFlags) and the xp-plan-reviewer .assign-pending
marker (TestPlanReviewerSetsAssignPending). See test_review_coverage.py for
the live xp-code-reviewer leg (the flag, its coverage record and qr_complete),
and test_review_cycle_done.py for the PostToolUse:Skill|Agent siblings, which
fire at launch and so set no commit-gating flag.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import review_records
import subagent_stop
from conftest import _HookTestCase


class TestSubagentStopReviewFlags(_HookTestCase):
    """SubagentStop: which review-related subagent completion means which flag."""

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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_quality_review_agent_type_sets_flag(self):
        """SubagentStop with agent_type 'xp-quality-review' sets flag.

        LATENT PATH — no production caller reaches it, because
        /xp-quality-review is inline and SubagentStop never fires for an
        inline skill. Kept, and pinned, because SubagentStop IS a completion
        signal: were the skill ever to become forked, this is the leg that
        would carry the flag. In production the flag rides the reviewer AGENT's
        completion instead (test_review_coverage.py). The _is_code_review
        siblings are latent for
        their own reason (Claude sends /code-review's workflow subagents with
        agent_type 'workflow-subagent' and an opaque agent_id, matching
        neither field), so read no test in this class as evidence that its
        path runs in production.
        """
        subagent_stop.run(
            self._stop_input("task-2", agent_type="xp-quality-review"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_code_review_agent_id_sets_flag(self):
        """SubagentStop with agent_id containing 'code-review' sets flag."""
        subagent_stop.run(
            self._stop_input("code-review-reuse-1", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_xp_code_reviewer_agent_does_not_set_flag(self):
        """Collision guard: our own xp-code-reviewer agent (spawned by
        /xp-quality-review) contains the substring 'code-review' but must NOT
        set the simplify flag — that half belongs to a /code-review workflow
        which may never have run. update_review_cycle_flags runs before the
        is_xp_agent skip, so the guard ('code-reviewer' not in name) is what
        prevents the false positive."""
        subagent_stop.run(
            self._stop_input("rev-1", agent_type="xp-code-reviewer"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_qualified_xp_code_reviewer_does_not_set_flag(self):
        """Plugin-qualified xp-agents:xp-code-reviewer is also excluded."""
        subagent_stop.run(
            self._stop_input("rev-2", agent_type="xp-agents:xp-code-reviewer"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])

    def test_xp_quality_reviewer_helper_does_not_set_flag(self):
        """story-006 symmetric guard: a future name like 'xp-quality-reviewer-helper'
        contains the substring 'quality-review' but must NOT set the
        quality_review_done flag. Mirrors `_is_code_review`'s 'code-reviewer not in'
        exclusion. Closes the parallel defect class in `update_review_cycle_flags`
        (debt b2389e3f725d)."""
        subagent_stop.run(
            self._stop_input("helper-1", agent_type="xp-quality-reviewer-helper"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])
        # Same guard must hold for agent_id-driven matches.
        subagent_stop.run(
            self._stop_input("xp-quality-reviewer-helper-9", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["quality_review_done"])

    def test_legacy_simplify_agent_type_no_longer_sets_flag(self):
        """Cutover: a subagent named 'simplify' no longer sets the flag."""
        subagent_stop.run(
            self._stop_input("task-9", agent_type="simplify"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])

    def test_regular_subagent_no_flag(self):
        """Regular subagent does not set any review flags."""
        subagent_stop.run(
            self._stop_input("task-3", agent_type="task"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_plan_subagent_no_review_flag(self):
        """Plan subagent writes plan marker but not review flags."""
        subagent_stop.run(
            self._stop_input("plan-1", agent_type="Plan"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        cycle = review_records.read_review_flags(self.smm_dir, "worktree-story-001")
        self.assertTrue(cycle["simplify_done"])

    def test_null_cwd_does_not_raise_and_falls_back_to_main(self):
        """An explicit `"cwd": null` SubagentStop payload must not raise
        (.get('cwd', '') returns None, not ''); the flag falls back to
        'main' so the hook still records and arms the review flag."""
        subagent_stop.run(
            self._stop_input("task-1", agent_type="code-review", cwd=None),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
