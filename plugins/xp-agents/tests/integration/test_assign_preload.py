#!/usr/bin/env python3
"""Integration tests for xp-assign preload with multi-story sprints.

Split from test_assign.py — preload-specific tests.
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
    write_smm_fixture,
)
from event_schema import EVENT_TYPE_DECISION


def _multi_story_sprint_worktree() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "User registration",
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
                "ready",
                file_domain=["src/admin/dashboard.py", "tests/test_dashboard.py"],
            ),
        ],
        sprint_id="sprint-001",
        started="2026-04-01",
    )


def _multi_story_sprint_solo_deps() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "User model",
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
                "ready",
                file_domain=["src/api/user.py"],
                dependencies=["story-001"],
            ),
        ],
        sprint_id="sprint-002",
        started="2026-04-01",
    )


def _multi_story_sprint_all_small() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "Fix typo",
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
                "ready",
                file_domain=["docs/README.md"],
            ),
        ],
        sprint_id="sprint-003",
        started="2026-04-01",
    )


def _multi_story_sprint_no_domains() -> str:
    return _sprint_json(
        [
            _s("story-001", "Feature A", "ready"),
            _s("story-002", "Feature B", "ready"),
        ],
        sprint_id="sprint-004",
        started="2026-04-01",
    )


def _multi_story_sprint_overlapping_domains() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "Auth flow",
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
                "ready",
                file_domain=["src/auth/reset.py", "src/shared/utils.py"],
            ),
        ],
        sprint_id="sprint-005",
        started="2026-04-01",
    )


_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestPreloadMultiStorySprint(_IntegrationTestCase):
    """Preload with various multi-story sprint configurations."""

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def test_preload_with_worktree_eligible_sprint(self):
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_with_dependency_chain_sprint(self):
        self._write_sprint(_multi_story_sprint_solo_deps())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_all_small_stories(self):
        self._write_sprint(_multi_story_sprint_all_small())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_no_file_domains(self):
        self._write_sprint(_multi_story_sprint_no_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_overlapping_domains(self):
        self._write_sprint(_multi_story_sprint_overlapping_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_without_sprint_no_sprint_file(self):
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SPRINT_FILE=", result.stdout)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_sprint_file_path_is_readable(self):
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found in output"
        sprint_file = Path(sprint_path)
        self.assertTrue(sprint_file.is_file())

        content = sprint_file.read_text()
        self.assertIn("sprint-001", content)
        self.assertIn("User registration", content)


class TestRenderedSprintForModeSelection(_IntegrationTestCase):
    """Verify rendered sprint content contains data for mode selection."""

    def _get_rendered_sprint(self, sprint_json: str) -> str:
        (self.smm_dir / "sprint.json").write_text(sprint_json)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found"
        return Path(sprint_path).read_text()

    def test_rendered_sprint_includes_file_domains(self):
        content = self._get_rendered_sprint(_multi_story_sprint_worktree())
        self.assertIn("src/auth/register.py", content)
        self.assertIn("src/admin/dashboard.py", content)

    def test_rendered_sprint_includes_dependencies(self):
        content = self._get_rendered_sprint(_multi_story_sprint_solo_deps())
        self.assertIn("story-001", content)

    def test_rendered_sprint_includes_sizes(self):
        content = self._get_rendered_sprint(_multi_story_sprint_all_small())
        self.assertIn("S", content)

    def test_rendered_sprint_shows_overlapping_domains(self):
        content = self._get_rendered_sprint(_multi_story_sprint_overlapping_domains())
        self.assertIn("src/shared/utils.py", content)

    def test_rendered_sprint_empty_domains_visible(self):
        content = self._get_rendered_sprint(_multi_story_sprint_no_domains())
        self.assertIn("Feature A", content)
        self.assertIn("Feature B", content)


class TestPreloadE2EPipeline(_IntegrationTestCase):
    """Full E2E: init SMM, seed sprint, run preload, verify output paths."""

    def _seed_plan(self, content: str = "# Test Plan\n## Step 1\nDo things\n"):
        plan_file = self.smm_dir / "test-plan.md"
        plan_file.write_text(content)
        (self.smm_dir / ".last-plan-path").write_text(str(plan_file))
        return plan_file

    def test_full_pipeline_with_smm_and_sprint(self):
        write_smm_fixture(
            self.smm_dir,
            intent=[("Build auth system", "goal")],
            constraints=[("TDD always", "convention")],
        )
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("SMM_FILE=", output)
        self.assertIn("SPRINT_FILE=", output)

        smm_dir_val = _extract_preload_var(output, "SMM_DIR")
        self.assertEqual(smm_dir_val, str(self.smm_dir))

    def test_full_pipeline_smm_only_no_sprint(self):
        write_smm_fixture(self.smm_dir, wisdom=["Small commits"])
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)
        self.assertIn("SMM_FILE=", result.stdout)
        self.assertNotIn("SPRINT_FILE=", result.stdout)

    def test_preload_plan_only_no_sprint(self):
        self._seed_plan()
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("PLAN_FILE=", output)
        self.assertNotIn("SPRINT_FILE=", output)

        plan_path = _extract_preload_var(output, "PLAN_FILE")
        assert plan_path is not None
        self.assertTrue(Path(plan_path).is_file())

    def test_preload_plan_before_sprint_in_output(self):
        self._seed_plan()
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        plan_pos = output.find("PLAN_FILE=")
        sprint_pos = output.find("SPRINT_FILE=")
        self.assertGreaterEqual(plan_pos, 0)
        self.assertGreaterEqual(sprint_pos, 0)
        self.assertLess(plan_pos, sprint_pos)

    def test_preload_clears_assign_pending_marker(self):
        marker = self.smm_dir / ".assign-pending"
        marker.write_text("gate-id")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_preload_outputs_plugin_root(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLUGIN_ROOT=", result.stdout)


class TestPreloadTeammateBatch(_IntegrationTestCase):
    """Narrowed xp-assign consumes the teammate batch from the preload (Python-
    computed) rather than inline scheduled-selection bash — symmetric with
    /xp-schedule's FRONTIER_IDS. TEAMMATE_STORY_IDS = in-progress stories whose
    execution_mode is teammate (the batch /xp-schedule already promoted)."""

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def test_emits_in_progress_teammate_stories_only(self):
        self._write_sprint(
            _sprint_json(
                [
                    _s("story-001", "A", "in-progress", execution_mode="teammate"),
                    _s("story-002", "B", "in-progress", execution_mode="teammate"),
                    _s("story-003", "C", "in-progress", execution_mode="solo"),
                    _s("story-004", "D", "scheduled", execution_mode="teammate"),
                ]
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = _extract_preload_var(result.stdout, "TEAMMATE_STORY_IDS")
        self.assertIsNotNone(ids, "TEAMMATE_STORY_IDS line must be emitted")
        self.assertEqual((ids or "").split(), ["story-001", "story-002"])

    def test_empty_when_no_teammate_in_progress(self):
        self._write_sprint(
            _sprint_json([_s("story-001", "A", "in-progress", execution_mode="solo")])
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = _extract_preload_var(result.stdout, "TEAMMATE_STORY_IDS")
        self.assertIsNotNone(ids, "line emitted even when empty")
        self.assertEqual((ids or "").strip(), "")

    def test_empty_when_no_sprint(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = _extract_preload_var(result.stdout, "TEAMMATE_STORY_IDS")
        self.assertEqual((ids or "").strip(), "")


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

    def _seed_tier_recommendation(self, story_id: str, model: str) -> None:
        ev = make_event(
            EVENT_TYPE_DECISION,
            topic=f"tier-recommendation-{story_id}",
            content=f"Suggested executor_model: {model} — test rationale",
            metadata={
                "recommended_model": model,
                "story_id": story_id,
                "advisory": True,
            },
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
