#!/usr/bin/env python3
"""Each close-skill preload appends the close-pipeline reference for its mode.

All four close skills source their Step 5 / 5b / 6 prose from a single
file at `scripts/_close_pipeline_shared.md`. Each preload `cat`s that
file at the end of its output so the LLM running the skill sees one
consistent set of shared instructions instead of four near-duplicate
copies.

Steps 4 and 4b live in a SECOND file, `scripts/_close_pipeline_review.md`,
appended (before the shared one) only by free/plan/sprint — the modes that
run those steps. Story-close defers both to its enclosing sprint-close and
appends the shared file alone, so the reference is mode-scoped by which
files a preload emits rather than by prose telling the reader to skip ahead.

These tests assert the preload-side mechanic: when a close-skill
preload runs, its stdout contains the reference's marker headings
and key phrases, per close mode (story/sprint/plan/free). The
`_SharedPreloadAssertions` mixin and the `_close_started_events` helper live
in `_close_preloads_helpers.py`, and the `_ReviewPipelineAssertions` mixin in
`_close_preloads_review_helpers.py` (neither test-collected), so the
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
import retro_metrics
from _bases import _PLUGIN_ROOT
from _close_preloads_helpers import _close_started_events, _SharedPreloadAssertions
from _close_preloads_review_helpers import _ReviewPipelineAssertions
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
        # the preload must NOT emit RUN_FULL_CODE_REVIEW. Step 4b's prose is
        # not appended either — see the review-steps inverse pin below.
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

    def test_does_not_emit_the_review_pipeline_steps(self):
        # Mode-scoped close reference. story-close runs neither Step 4
        # (Security Review — the enclosing sprint-close covers this diff) nor
        # Step 4b (the broad workflow /code-review, which never fires at story
        # close: the preload does not even compute its gate flag, pinned
        # above). Both steps live in `_close_pipeline_review.md`, which only
        # free/plan/sprint `cat`. Emitting them here spent context on steps
        # this mode is documented to skip.
        #
        # Pinned on the EMITTED STDOUT, not on the preload source: the source
        # check would pass the moment the `cat` line is absent, even if the
        # steps had been left inline in the file story-close still reads.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for absent in (
            "### Step 4: Security Review",
            "### Step 4b: Full code review (conditional)",
            'Skill(skill: "security-review"',
            '"kind":"security"',
        ):
            with self.subTest(absent=absent):
                self.assertNotIn(
                    absent,
                    result.stdout,
                    f"story-close preload must not emit {absent!r} — Steps 4 "
                    "and 4b belong to the modes that run them",
                )

    def test_emits_close_started_event_story(self):
        # story-close records its cycle in the log like every other mode: the
        # id it writes to the marker is only on disk until the SessionStart
        # sweep, and a close cycle that left no trace cannot be audited after
        # the fact.
        #
        # This test replaced an inverse-pin ("story-close must NOT emit
        # close_started"). The invariant that pin was really protecting is
        # asserted directly below instead — the mode field, not the event's
        # absence, is what keeps the security rule honest.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        cycle_id = _extract_preload_var(result.stdout, "CLOSE_CYCLE_ID")
        events = _close_started_events(self.smm_dir)
        self.assertEqual(
            len(events), 1, f"expected 1 close_started event, got {events!r}"
        )
        metadata = events[0].get("metadata") or {}
        self.assertEqual(metadata.get("close_mode"), "story")
        self.assertEqual(metadata.get("close_cycle_id"), cycle_id)

    def test_close_started_does_not_claim_a_security_review_ran(self):
        # The load-bearing half of the pin above. `security_close_ran` scopes
        # the retro's security_checks=0 Courage rule to the close modes that
        # actually run /security-review, and story-close is not one of them —
        # the enclosing sprint-close covers its diff. The scoping keys on
        # metadata.close_mode, so a story-close close_started must never be
        # counted as a security-bearing close.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(
            "story",
            retro_metrics._SECURITY_CLOSE_MODES,
            "story-close does not run /security-review; adding it to the "
            "security-bearing modes would silence the security_checks=0 rule "
            "for every story-close-only session",
        )
        events = _close_started_events(self.smm_dir)
        self.assertTrue(
            all(
                (e.get("metadata") or {}).get("close_mode")
                not in retro_metrics._SECURITY_CLOSE_MODES
                for e in events
            ),
            f"story-close must not emit a security-bearing close_mode: {events!r}",
        )


class TestSprintClosePreloadEmitsShared(
    _ReviewPipelineAssertions, _SharedPreloadAssertions, _IntegrationTestCase
):
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


class TestPlanClosePreloadEmitsShared(
    _ReviewPipelineAssertions, _SharedPreloadAssertions, _IntegrationTestCase
):
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


class TestFreeClosePreloadEmitsShared(
    _ReviewPipelineAssertions, _SharedPreloadAssertions, _IntegrationTestCase
):
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
