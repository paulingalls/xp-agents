#!/usr/bin/env python3
"""Integration tests for xp-assign preload with multi-story sprints.

Split from test_assign.py — preload-specific tests.

Split from test_assign_preload.py — tier-picker & solo-target selection
tests (as opposed to sprint-shape / rendering / e2e-pipeline output).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


import markers
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


class TestPreloadTierPicker(_IntegrationTestCase):
    """story-003: the preload emits the Layer-3 decision inputs — the session
    default tier (TEAMMATE_DEFAULT) and the plan-reviewer's per-story
    recommendation (RECOMMENDED_TIER) — both computed for the SAME story the
    skill's pre-flight will spawn (lowest-id un-spawned teammate story).

    TARGET-IDENTITY INVARIANT (plan-review assumption 9b63d2e8efcc): the
    preload pins RECOMMENDED_TIER_STORY so a future divergence between the
    preload's target and the skill's spawn target is caught.
    """

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def _single_teammate_sprint(self, story_id: str = "story-001") -> str:
        return _sprint_json(
            [_s(story_id, "Build feature", "in-progress", execution_mode="teammate")]
        )

    def _seed_tier_recommendation(
        self, story_id: str, model: str, effort: str | None = None
    ) -> None:
        metadata = {
            "recommended_model": model,
            "story_id": story_id,
            "advisory": True,
        }
        if effort is not None:
            metadata["recommended_effort"] = effort
        ev = make_event(
            EVENT_TYPE_DECISION,
            topic=f"tier-recommendation-{story_id}",
            content=f"Suggested executor_model: {model} — test rationale",
            metadata=metadata,
        )
        self._seed_events([ev])

    def test_emits_recommended_tier_and_pins_target(self):
        """AC#5: a seeded tier-recommendation surfaces as RECOMMENDED_TIER for
        the story the skill will spawn — target identity pinned."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_tier_recommendation("story-001", "sonnet")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "sonnet"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-001"
        )

    def test_emits_recommended_effort_when_present(self):
        """story-004 AC1: a recommendation carrying recommended_effort surfaces
        as RECOMMENDED_EFFORT (same winning event as RECOMMENDED_TIER)."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_tier_recommendation("story-001", "sonnet", effort="xhigh")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_EFFORT"), "xhigh"
        )

    def test_recommended_effort_empty_when_absent(self):
        """story-004 AC2: a recommendation with no effort → RECOMMENDED_EFFORT is
        emitted but empty (the skill then omits --effort)."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_tier_recommendation("story-001", "sonnet")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (_extract_preload_var(result.stdout, "RECOMMENDED_EFFORT") or ""), ""
        )

    def test_recommended_effort_empty_on_retraction(self):
        """A later null-model retraction wins the reverse-scan; it carries no
        effort key, so RECOMMENDED_EFFORT is empty — effort travels with the
        winning tier event, never a stale earlier one."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": "opus",
                        "recommended_effort": "max",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": None,
                        "retracted": True,
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "none"
        )
        self.assertEqual(
            (_extract_preload_var(result.stdout, "RECOMMENDED_EFFORT") or ""), ""
        )

    def test_emits_teammate_default_from_marker(self):
        """AC#5: the session default tier is emitted for the skill to act on."""
        self._write_sprint(self._single_teammate_sprint())
        markers.write_teammate_config(self.smm_dir, "opus")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "TEAMMATE_DEFAULT"), "opus"
        )

    def test_default_inherit_when_no_marker(self):
        """No TEAMMATE_CONFIG marker → fail-safe to inherit (today's behavior)."""
        self._write_sprint(self._single_teammate_sprint())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "TEAMMATE_DEFAULT"), "inherit"
        )

    def test_no_recommendation_yields_none(self):
        """plan-reviewer omit-when-ambiguous case → RECOMMENDED_TIER=none."""
        self._write_sprint(self._single_teammate_sprint())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "none"
        )

    def test_in_agent_recommendation_passes_through(self):
        """`in-agent` is a valid recommendation token the preload emits verbatim
        (the skill maps it to the no-spawn branch)."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_tier_recommendation("story-001", "in-agent")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "in-agent"
        )

    def test_target_is_lowest_id_unspawned(self):
        """Two un-spawned teammate stories → target is the lowest id, and its
        recommendation (not the sibling's) is emitted."""
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="teammate"),
                    _s("story-002", "B", "in-progress", execution_mode="teammate"),
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
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-001"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "haiku"
        )

    def test_latest_recommendation_wins(self):
        """Two events for the same topic → the latest (tail) recommendation wins."""
        self._write_sprint(self._single_teammate_sprint())
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
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": "opus",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "opus"
        )

    def test_retraction_overrides_earlier_recommendation(self):
        """debt d5697631a002: a later same-topic retraction (recommended_model
        null) beats an earlier real recommendation → RECOMMENDED_TIER=none. The
        reverse-scan must honor the LATEST matching event, not skip a null-model
        one and fall back to the stale earlier pick."""
        self._write_sprint(self._single_teammate_sprint())
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": "opus",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    metadata={
                        "recommended_model": None,
                        "retracted": True,
                        "story_id": "story-001",
                        "advisory": True,
                    },
                ),
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "none"
        )

    def test_stale_prior_sprint_recommendation_is_scoped_out(self):
        """A tier-recommendation from a PRIOR sprint that reused the same
        per-sprint story id must NOT leak into the current sprint's pick.
        Per-sprint story ids (story-001...) are reused every sprint, so the
        scan is scoped to events on/after the current sprint's `started`
        date — mirroring retro_metrics._event_in_sprint_window."""
        self._write_sprint(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Build feature",
                        "in-progress",
                        execution_mode="teammate",
                    )
                ],
                started="2026-06-01",
            )
        )
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    ts="2026-05-01T00:00:00+00:00",
                    metadata={
                        "recommended_model": "opus",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                )
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "none"
        )

    def test_in_window_recommendation_survives_scoping(self):
        """A recommendation written on/after the sprint `started` date is in
        the current sprint window and surfaces normally."""
        self._write_sprint(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Build feature",
                        "in-progress",
                        execution_mode="teammate",
                    )
                ],
                started="2026-06-01",
            )
        )
        self._seed_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="tier-recommendation-story-001",
                    ts="2026-06-15T00:00:00+00:00",
                    metadata={
                        "recommended_model": "sonnet",
                        "story_id": "story-001",
                        "advisory": True,
                    },
                )
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "sonnet"
        )

    def test_no_recommendation_for_solo_target_yields_none(self):
        """Solo target with no tier-recommendation → RECOMMENDED_TIER=none, but
        the solo story is still pinned as the target (story-008: the solo
        execution-shape decision reaches xp-assign)."""
        self._write_sprint(
            _sprint_json([_s("story-001", "A", "in-progress", execution_mode="solo")])
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER_STORY"), "story-001"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "RECOMMENDED_TIER"), "none"
        )


class TestPreloadSoloTarget(_IntegrationTestCase):
    """story-008: when there is no teammate batch, a single in-progress SOLO
    story is the in-place execution-shape target. SOLO_TARGET names it so the
    skill pre-flight can run the decision table for solo (in-agent vs in-place
    spawn) instead of hard-stopping."""

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

    def test_solo_target_empty_when_teammate_batch_present(self):
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
        # A live teammate batch owns the target; the solo story does not surface.
        self.assertEqual((_extract_preload_var(result.stdout, "SOLO_TARGET") or ""), "")

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
