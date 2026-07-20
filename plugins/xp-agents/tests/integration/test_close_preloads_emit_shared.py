#!/usr/bin/env python3
"""Each close-skill preload appends the shared close-pipeline reference.

All four close skills source their Step 5 / 5b / 6 prose from a single
file at `scripts/_close_pipeline_shared.md`. Each preload `cat`s that
file at the end of its output so the LLM running the skill sees one
consistent set of shared instructions instead of four near-duplicate
copies.

These tests assert the preload-side mechanic: when a close-skill
preload runs, its stdout contains the shared content's marker headings
and key phrases, per close mode (story/sprint/plan/free). The shared
`_SharedPreloadAssertions` mixin and `_close_started_events` helper
live in `_close_preloads_helpers.py` (not test-collected) so all four
mode-specific TestCase classes below share one copy.

The cross-mode CLOSE_START_TS emission check, plan/free SKIP-note
drop, shared-pipeline section ordering coherence, and the
project-generic constraint on shipped files live in
`test_close_preloads_emit_shared_project_generic.py` and
`test_close_preloads_emit_shared_cross_mode.py`.

Auto-merge gate, TEST_COMMAND wiring, and Step 6 count-concerns
realistic E2E tests live in test_close_merge_gate.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import markers
from _bases import _PLUGIN_ROOT
from _close_preloads_helpers import _close_started_events, _SharedPreloadAssertions
from conftest import _extract_preload_var, _IntegrationTestCase


class TestStoryClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def test_emits_step4_close_cycle_active_marker_write(self):
        # Inverse-pin: story-close NEVER runs Step 4 (Security Review) —
        # the enclosing sprint-close covers it. So the preload source
        # must NOT invoke `write_marker CLOSE_CYCLE_ACTIVE`, and after
        # running, no marker file must land on disk.
        source = self._PRELOAD.read_text()
        self.assertNotIn(
            "write_marker CLOSE_CYCLE_ACTIVE",
            source,
            "story-close preload must NOT arm the close-cycle marker "
            "(no security-review, no marker arming)",
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        self.assertFalse(
            marker_path.is_file(),
            f"story-close preload must not create marker at {marker_path}",
        )

    def test_does_not_emit_run_full_code_review_flag(self):
        # Inverse-pin: story-close runs /xp-quality-review only (self-find);
        # the broad Step 4b workflow /code-review never runs at story close, so
        # the preload must NOT emit RUN_FULL_CODE_REVIEW. The shared Step 4b
        # prose is still catted (gated on the absent flag → skipped).
        source = self._PRELOAD.read_text()
        self.assertNotIn(
            "close-review-gate",
            source,
            "story-close preload must NOT compute the Step 4b review gate",
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(
            _extract_preload_var(result.stdout, "RUN_FULL_CODE_REVIEW"),
            "story-close preload must not emit RUN_FULL_CODE_REVIEW",
        )

    def test_does_not_emit_close_started_event(self):
        # Inverse-pin: story-close has no Step 4 security review, so its
        # preload MUST NOT emit a close_started event. Sourced by
        # retro_metrics.security_close_ran to scope the security_checks=0
        # Courage rule to security-bearing close modes only.
        source = self._PRELOAD.read_text()
        self.assertNotIn(
            "emit_close_started_event",
            source,
            "story-close preload must NOT emit close_started",
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        events = _close_started_events(self.smm_dir)
        self.assertEqual(
            events,
            [],
            f"story-close preload must not emit close_started events, got {events!r}",
        )


class TestSprintClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"

    def test_emits_run_full_code_review_flag(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(
            _extract_preload_var(result.stdout, "RUN_FULL_CODE_REVIEW"),
            "sprint-close preload must emit RUN_FULL_CODE_REVIEW for Step 4b",
        )

    def test_emits_close_started_event_sprint(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        cycle_id = _extract_preload_var(result.stdout, "CLOSE_CYCLE_ID")
        events = _close_started_events(self.smm_dir)
        self.assertEqual(
            len(events), 1, f"expected 1 close_started event, got {events!r}"
        )
        md = events[0].get("metadata") or {}
        self.assertEqual(md.get("close_mode"), "sprint")
        self.assertEqual(md.get("close_cycle_id"), cycle_id)


class TestPlanClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: plan-close preload now emits the shared content too.

    Step 5b previously skipped on the rationale that story+sprint close
    already auto-resolved everything resolvable. Multi-sprint plans
    break that assumption — concerns from sprint N can be MAYBE-
    ADDRESSED by commits in sprint N+1, but sprint N's close window has
    already passed when those commits land. Plan-close is the last
    chance to catch slipped-through matches.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"

    def test_emits_run_full_code_review_flag(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(
            _extract_preload_var(result.stdout, "RUN_FULL_CODE_REVIEW"),
            "plan-close preload must emit RUN_FULL_CODE_REVIEW for Step 4b",
        )

    def test_emits_close_started_event_plan(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        cycle_id = _extract_preload_var(result.stdout, "CLOSE_CYCLE_ID")
        events = _close_started_events(self.smm_dir)
        self.assertEqual(
            len(events), 1, f"expected 1 close_started event, got {events!r}"
        )
        md = events[0].get("metadata") or {}
        self.assertEqual(md.get("close_mode"), "plan")
        self.assertEqual(md.get("close_cycle_id"), cycle_id)


class TestFreeClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: free-close preload now emits the shared content too.

    Step 5b previously skipped on the (incorrect) rationale that free
    branches don't carry sprint/plan-tracked concerns. Demonstrably
    wrong — free branches routinely fix tracked concerns when used for
    follow-up work (cleanup, docs, fixes). The triage_preload helper
    looks for files-touched overlap with open concerns and is mode-
    agnostic; nothing about free-mode justifies the skip.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"

    def test_emits_run_full_code_review_flag(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(
            _extract_preload_var(result.stdout, "RUN_FULL_CODE_REVIEW"),
            "free-close preload must emit RUN_FULL_CODE_REVIEW for Step 4b",
        )

    def test_emits_close_started_event_free(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        cycle_id = _extract_preload_var(result.stdout, "CLOSE_CYCLE_ID")
        events = _close_started_events(self.smm_dir)
        self.assertEqual(
            len(events), 1, f"expected 1 close_started event, got {events!r}"
        )
        md = events[0].get("metadata") or {}
        self.assertEqual(md.get("close_mode"), "free")
        self.assertEqual(md.get("close_cycle_id"), cycle_id)


if __name__ == "__main__":
    unittest.main()
