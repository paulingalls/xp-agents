#!/usr/bin/env python3
"""Tests for SubagentStart sprint-aware tiers and housekeeper handler.

Split from test_subagent_tiers.py -- sprint context and housekeeper tests.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import SAMPLE_SPRINT_MD as _SAMPLE_SPRINT
from conftest import (
    _HookTestCase,
    adopt_try_event,
    drop_try_event,
    make_event,
    triage_event,
    write_smm_fixture,
)
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)

_ADOPTED_TRIES = "### Adopted Tries"
_DEFERRED_DROPPED = "### Deferred / Dropped"
_TRIAGE = "### Triage: Adopted / Deferred"


def _section(block: str, heading: str) -> str:
    """The lines under *heading* in the work-selection block, or "" if absent.

    Substring checks against the whole block cannot tell a leak from a correct
    placement — a triage defer that landed under the wrong heading is still
    "in" the block. Every lane assertion below is scoped to one section.
    """
    lines = block.splitlines()
    if heading not in lines:
        return ""
    start = lines.index(heading) + 1
    body: list[str] = []
    for line in lines[start:]:
        # Any heading ends the section — `###` for the next bucket, and the
        # bare `#` of the XP-values doc that `run` concatenates after the
        # block. Without the latter, the LAST bucket's body would swallow the
        # values text and every assertion scoped to it would be junk.
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


# ===========================================================================
# Sprint-aware tier tests (M10)
# ===========================================================================


class TestSubagentStartSprintTiers(_HookTestCase):
    """M10: Sprint-aware tiered injection."""

    def setUp(self):
        super().setUp()
        import subagent_start

        self.subagent_start = subagent_start
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth module fragile", "concern", "problem")],
            wisdom=["TDD always"],
        )
        sprint_file = self.smm_dir / "sprint.json"
        sprint_file.write_text(_SAMPLE_SPRINT)

    def test_plan_reviewer_gets_values_only(self):
        """xp-plan-reviewer gets XP values only (data from preload)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)
        # Should NOT get SMM content (that comes from preload)
        self.assertNotIn("Ship v1", result)

    def test_retrospective_handler_injects_paths(self):
        """xp-retrospective injects SMM_DIR + RETRO_INPUT."""
        for agent_type in (
            "xp-retrospective",
            "xp-agents:xp-retrospective",
        ):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "retro-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                assert result is not None
                self.assertIn(f"SMM_DIR={self.smm_dir}", result)
                self.assertIn(
                    f"RETRO_INPUT={self.smm_dir}/.retro-input.json",
                    result,
                )
                self.assertIn("Extreme Programming", result)
                self.assertNotIn("Ship v1", result)

    def test_close_reviewer_has_no_dedicated_handler(self):
        """xp-close-reviewer reads its review fields (mode, source_branch,
        target_branch, diff_command) from the Agent prompt sections the
        close skill embeds — never via SubagentStart injection."""
        for agent_type in (
            "xp-close-reviewer",
            "xp-agents:xp-close-reviewer",
        ):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "close-rev-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                # No special injection — falls through to the default path
                # (XP values only, no REVIEW_INPUT line).
                if result is not None:
                    self.assertNotIn("REVIEW_INPUT=", result)

    def test_sprint_reviewer_gets_values_only(self):
        """xp-sprint-reviewer gets XP values only."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "review-1",
                "agent_type": "xp-sprint-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)
        self.assertNotIn("Ship v1", result)

    def test_custom_agent_type_gets_full_smm(self):
        """Custom agent types get full SMM (default tier)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "worker-1",
                "agent_type": "backend-worker",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Ship v1", result)
        self.assertNotIn("Teammate Guide", result)

    def test_general_purpose_gets_reference_not_eager_smm(self):
        """A general-purpose agent is the generic reference tier: it gets a
        pointer to the SMM, not the eager full render. Even with a sprint
        active, no SMM/sprint content is injected — it self-serves on demand if
        its task writes code. (Custom/unknown types still get full SMM — see
        test_custom_agent_type_gets_full_smm.)"""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "teammate-1",
                "agent_type": "general-purpose",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn(f"SMM_DIR={self.smm_dir}", result)
        self.assertNotIn("Ship v1", result)
        self.assertNotIn("sprint-001", result)

    def test_plan_reviewer_no_sprint_still_gets_values(self):
        """xp-plan-reviewer gets values even without sprint.json."""
        (self.smm_dir / "sprint.json").unlink()
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_code_reviewer_gets_full_smm(self):
        """xp-code-reviewer gets full SMM."""
        for agent_type in (
            "xp-code-reviewer",
            "xp-agents:xp-code-reviewer",
        ):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "reviewer-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                assert result is not None
                self.assertIn("Intent", result)
                self.assertIn("Ship v1", result)
                self.assertIn("Constraints", result)
                self.assertIn("Python 3.10+", result)
                self.assertIn("Risks", result)
                self.assertIn("Wisdom", result)
                self.assertIn("Extreme Programming", result)

    def test_other_xp_agents_get_values(self):
        """xp-* agents not in dispatch table get XP values."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "nav-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_explore_unchanged(self):
        """Explore still gets Intent + Constraints only."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "explore-1",
                "agent_type": "Explore",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertNotIn("sprint-001", result)

    def test_default_agent_unchanged(self):
        """Default (non-xp, non-Explore) gets full SMM."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Intent", result)
        self.assertIn("Risks", result)
        self.assertNotIn("sprint-001", result)


# ===========================================================================
# Housekeeper inline-agent handler tests
# ===========================================================================


class TestSubagentStartHousekeeper(_HookTestCase):
    """xp-housekeeper handler writes curation input and injects paths."""

    def setUp(self):
        super().setUp()
        import subagent_start

        self.subagent_start = subagent_start
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth module fragile", "concern", "problem")],
            wisdom=["TDD always"],
        )

    def _run_housekeeper(self, agent_type: str = "xp-agents:xp-housekeeper") -> str:
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "housekeeper-1",
                "agent_type": agent_type,
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        return result

    def test_writes_curation_input_and_injects_paths(self):
        """Handler writes .curation-input.json and advertises paths."""
        for agent_type in (
            "xp-housekeeper",
            "xp-agents:xp-housekeeper",
        ):
            with self.subTest(agent_type=agent_type):
                curation_file = self.smm_dir / ".curation-input.json"
                curation_file.unlink(missing_ok=True)
                result = self._run_housekeeper(agent_type)
                self.assertTrue(curation_file.exists())
                data = json.loads(curation_file.read_text())
                self.assertIn("current_smm", data)
                self.assertIn("new_since_last_curation", data)
                self.assertIn(f"SMM_DIR={self.smm_dir}", result)
                self.assertIn(f"CURATION_INPUT={curation_file}", result)
                self.assertIn("Extreme Programming", result)

    def test_work_selection_block_when_events_present(self):
        """Session work-selection events produce a block."""
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="retro-try-fix-thing",
                    content="Adopted retro Try: fix the thing",
                ),
                make_event(
                    EVENT_TYPE_STATUS,
                    content=("Deferred retro Try: questions_stop_gate"),
                    metadata={"disposition": "deferred"},
                ),
                make_event(EVENT_TYPE_GOAL, content="Sprint session"),
            ]
        )
        result = self._run_housekeeper()
        self.assertIn("## Session Work Selection", result)
        self.assertIn("fix the thing", result)
        self.assertIn("questions_stop_gate", result)
        self.assertIn("Sprint session", result)

    def test_no_work_selection_block_when_absent(self):
        """Without work-selection events, no block is emitted."""
        self._write_events(
            [
                make_event(EVENT_TYPE_CUSTOMER_INPUT, content="unrelated event"),
                make_event(EVENT_TYPE_CONCERN, content="unrelated concern"),
            ]
        )
        result = self._run_housekeeper()
        self.assertNotIn("## Session Work Selection", result)

    # -- Lane separation -----------------------------------------------------
    # Both lanes write `status` events with the same disposition vocabulary, so
    # the disposition ALONE cannot say which lane an event came from. The events
    # below all go through the REAL writer (conftest fixtures), because the shape
    # is the whole point: a hand-rolled fixture would encode the shape its author
    # believed the writer produces, which is how this reader stayed green while
    # leaking triage items into a retro-Try bucket.

    def _seed_triage_targets(self) -> tuple[dict, dict]:
        """A concern and a debt for the triage lane to dispose of."""
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Flaky auth test", severity="medium"
        )
        debt = make_event(EVENT_TYPE_DEBT, content="Legacy shim in loader")
        self._write_events([concern, debt])
        return concern, debt

    def test_triage_dispositions_stay_out_of_the_retro_buckets(self):
        """A triage-lane defer/drop/adopt disposes of a DEBT or CONCERN, not a
        retro Try. Before the lane check, the deferred/dropped arm matched on
        disposition alone and paraded them under "Deferred / Dropped" — the
        housekeeper read them as Tries the session had declined."""
        concern, debt = self._seed_triage_targets()
        triage_event(self.smm_dir, "triage-defer", concern["id"])
        triage_event(self.smm_dir, "triage-drop", debt["id"])
        triage_event(self.smm_dir, "triage-adopt", concern["id"])

        result = self._run_housekeeper()
        retro_buckets = _section(result, _DEFERRED_DROPPED) + _section(
            result, _ADOPTED_TRIES
        )
        self.assertNotIn("Triage:", retro_buckets)
        self.assertNotIn(concern["id"][:8], retro_buckets)
        self.assertNotIn(debt["id"][:8], retro_buckets)

    def test_triage_adoptions_are_shown_under_their_own_heading(self):
        """Excluding triage items from the retro buckets must not DELETE them:
        the housekeeper's only signal that a concern/debt was adopted is this
        block (triage events are `status`, which materialize buckets nowhere).
        A drop needs no bucket — it closes its target, which reaches the
        housekeeper through the resolutions."""
        concern, debt = self._seed_triage_targets()
        triage_event(self.smm_dir, "triage-adopt", concern["id"])
        triage_event(self.smm_dir, "triage-defer", debt["id"])

        triage = _section(self._run_housekeeper(), _TRIAGE)
        self.assertIn("Flaky auth test", triage)
        self.assertIn("Legacy shim in loader", triage)

    def test_retro_drop_is_still_reported_as_dropped(self):
        """The trap: this bucket is "Deferred / **Dropped**", so a retro DROP
        must keep appearing in it. `intent_disposition()` returns None for a
        drop by design (a drop closes via metadata.resolves), so mirroring the
        intent-lane predicate verbatim here would silently delete retro drops
        with every test still green."""
        self._write_events([])
        drop_try_event(
            self.smm_dir, "aaaaaaaaaaaa", content="Dropped Try: split the god module"
        )

        dropped = _section(self._run_housekeeper(), _DEFERRED_DROPPED)
        self.assertIn("split the god module", dropped)

    def test_lane_tag_beats_a_drifted_adopt_topic(self):
        """The tag is the truth, the slug is not. A correctly-tagged retro
        adoption whose LLM-authored topic drifts off the `retro-try-` prefix was
        silently invisible to the housekeeper."""
        self._write_events([])
        adopt_try_event(
            self.smm_dir,
            "bbbbbbbbbbbb",
            topic="adopt-the-carried-item",
            content="Adopted Try: run the suite before staging",
        )

        adopted = _section(self._run_housekeeper(), _ADOPTED_TRIES)
        self.assertIn("run the suite before staging", adopted)

    def test_session_boundary_filters_old_events(self):
        """retro-try-* decisions before the session_started anchor are ignored."""
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_DECISION,
                    topic="retro-try-old-item",
                    content=("Adopted retro Try: old item from prior session"),
                ),
                make_event(
                    EVENT_TYPE_SESSION_STARTED,
                    content="current session started",
                ),
            ]
        )
        result = self._run_housekeeper()
        self.assertNotIn("## Session Work Selection", result)
        self.assertNotIn("old item from prior session", result)


if __name__ == "__main__":
    unittest.main()
