#!/usr/bin/env python3
"""Integration tests for the xp-assign preload's SOLO target selection.

Split from test_assign_preload_tier_target.py when it crossed the 500-line
cap; that file keeps the tier-picker (which recommendation resolves for the
target), this one keeps target SELECTION (which story is the target at all).
Both drive the same preload — the seam is the question each asks.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


from _bases import _PLUGIN_ROOT
from conftest import (
    _extract_preload_var,
    _IntegrationTestCase,
    _s,
    _sprint_json,
    make_event,
)
from event_schema import EVENT_TYPE_DECISION

_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestPreloadSoloTarget(_IntegrationTestCase):
    """story-008: a single in-progress SOLO story is the in-place execution-
    shape target, whether or not a teammate batch is live. SOLO_TARGET names it
    so the skill pre-flight can run the decision table for solo (in-agent vs
    in-place spawn) instead of hard-stopping. Selection is SOLO-FIRST: the solo
    story drains before the batch resumes, so a spawn never checks out a base
    branch in a checkout an in-place teammate is committing to."""

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def test_single_solo_in_progress_surfaces_as_solo_target(self):
        self._write_sprint(
            _sprint_json([_s("story-001", "A", "in-progress", execution_mode="solo")])
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SOLO_TARGET"), "story-001"
        )
        # The solo story is the tier-lookup target too (pin).
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-001"
        )

    def test_solo_target_surfaces_alongside_a_teammate_batch(self):
        """A mixed frontier (teammate batch + one in-progress solo story) is
        routable: SOLO_TARGET names the solo story.

        This RETIRES the earlier teammate-first invariant ("a live teammate
        batch owns the target; the solo story does not surface"). That coupling
        made a pulled-forward solo story unassignable for as long as any
        teammate was in flight — the skill would resolve a teammate while the
        lead held the solo story's plan, the exact mispairing the skill warns
        about. Only the batch coupling is retired; the >1-solo ambiguity guard
        below still holds.
        """
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="teammate"),
                    _s("story-002", "B", "in-progress", execution_mode="solo"),
                ]
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SOLO_TARGET"), "story-002"
        )
        # The batch itself is untouched — solo-first reorders, it does not drop.
        self.assertEqual(
            _extract_preload_var(result.stdout, "TEAMMATE_STORY_IDS"), "story-001"
        )

    def test_mixed_frontier_tier_lookup_resolves_the_solo_story(self):
        """Solo-first: on a mixed frontier the tier lookup targets the SOLO
        story, not the first un-spawned teammate — so the preload's advertised
        target agrees with the target the skill resolves. On a mismatch the
        skill forces RECOMMENDED_TIER=none and the story spawns at the default
        tier, silently losing the plan-reviewer's pick."""
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="teammate"),
                    _s("story-002", "B", "in-progress", execution_mode="solo"),
                ]
            )
        )
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": "haiku",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-002",
                    metadata={
                        "recommended_model": "opus",
                        "story_id": "story-002",
                        "advisory": True,
                    },
                ),
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-002"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "opus"
        )

    def test_multiple_solo_ambiguity_guard_holds_under_a_teammate_batch(self):
        """The ambiguity guard is independent of the batch: >1 in-progress solo
        is unresolvable whether or not teammates are live, and the teammate flow
        is what remains. Pins that solo-first removed ONLY the batch coupling."""
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="teammate"),
                    _s("story-002", "B", "in-progress", execution_mode="solo"),
                    _s("story-003", "C", "in-progress", execution_mode="solo"),
                ]
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((_extract_preload_var(result.stdout, "SOLO_TARGET") or ""), "")
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-001"
        )

    def test_solo_target_empty_when_multiple_solo_in_progress(self):
        """A solo frontier promotes ONE story; >1 in-progress solo is ambiguous
        → no solo target (fail safe to empty, the skill stops)."""
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="solo"),
                    _s("story-002", "B", "in-progress", execution_mode="solo"),
                ]
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((_extract_preload_var(result.stdout, "SOLO_TARGET") or ""), "")

    def test_solo_target_empty_when_no_sprint(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((_extract_preload_var(result.stdout, "SOLO_TARGET") or ""), "")

    def test_solo_target_recommended_tier_resolves(self):
        """The plan-reviewer's recommendation for the solo story surfaces as
        RECOMMENDED_TIER (the tier lookup runs for the solo target)."""
        self._write_sprint(
            _sprint_json(
                [_s("story-001", "A", "in-progress", execution_mode="solo")],
                started="2026-04-01",
            )
        )
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    ts="2026-04-15T00:00:00+00:00",
                    metadata={
                        "recommended_model": "haiku",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                )
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "haiku"
        )


if __name__ == "__main__":
    unittest.main()
