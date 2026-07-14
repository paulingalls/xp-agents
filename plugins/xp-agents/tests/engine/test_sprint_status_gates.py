#!/usr/bin/env python3
"""Gate predicates derived from sprint.json state.

Split from test_sprint_status.py at the commit that pushed it past the
500-line cap. Covers schedule_gate_active (the pre-promotion window the
/xp-schedule gates fire on) and in_progress_is_teammate.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)


class TestScheduleGateActive(_SMMTestCase):
    """schedule_gate_active{,_data}: the trigger the /xp-schedule gates fire
    on — scheduled stories exist AND no story is in motion (in-progress,
    reviewing, or closing). That is exactly the "work-selection scheduled
    work, no frontier promoted yet" window; /xp-schedule is the sole
    legitimate exit (promotes scheduled->in-progress). The in-motion guard
    keeps the gate quiet during the /xp-story-close window so review-cycle
    fixes to the closing story aren't blocked by a demand to promote the
    still-scheduled next frontier.
    """

    def _write(self, stories):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_active_when_scheduled_and_none_in_progress(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="scheduled")])
        self.assertTrue(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_any_in_progress(self):
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="in-progress"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_story_closing(self):
        """The /xp-story-close window: one story closing, next still
        scheduled. The gate must stay quiet so review-cycle fixes to the
        closing story aren't blocked by a /xp-schedule demand that would
        wrongly promote the next frontier mid-close.
        """
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="closing"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_story_reviewing(self):
        """The /xp-accept review window: one story reviewing, next still
        scheduled. Same as closing — fix-cycle writes belong to the
        reviewing story, not the next frontier.
        """
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="reviewing"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_no_scheduled(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="in-progress")])
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_no_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_data_twin_is_pure(self):
        import sprint_status

        active = _make_sprint(stories=[_make_story(status="scheduled")])
        blocked = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled"),
                _make_story(id="story-002", status="in-progress"),
            ]
        )
        closing = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled"),
                _make_story(id="story-002", status="closing"),
            ]
        )
        self.assertTrue(sprint_status.schedule_gate_active_data(active))
        self.assertFalse(sprint_status.schedule_gate_active_data(blocked))
        self.assertFalse(sprint_status.schedule_gate_active_data(closing))


class TestInProgressIsTeammate(_SMMTestCase):
    """in_progress_is_teammate{,_data}: True iff any in-progress story is
    execution_mode=='teammate'. The signal subagent_stop's plan-review gate
    keys on — only teammate-mode plans need /xp-assign, so solo/unset plan
    reviews must leave no .assign-pending marker. Conservative default False.
    """

    def _write(self, stories):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_true_when_in_progress_teammate(self):
        import sprint_store

        self._write(
            [
                _make_story(
                    id="story-001", status="in-progress", execution_mode="teammate"
                )
            ]
        )
        self.assertTrue(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_in_progress_solo(self):
        import sprint_store

        self._write(
            [_make_story(id="story-001", status="in-progress", execution_mode="solo")]
        )
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_execution_mode_unset(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="in-progress")])
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_teammate_but_not_in_progress(self):
        import sprint_store

        # A teammate-mode story still in reviewing is not the just-planned unit.
        self._write(
            [_make_story(id="story-001", status="reviewing", execution_mode="teammate")]
        )
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_no_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_data_twin_is_pure(self):
        import sprint_status

        teammate = _make_sprint(
            stories=[_make_story(status="in-progress", execution_mode="teammate")]
        )
        solo = _make_sprint(
            stories=[_make_story(status="in-progress", execution_mode="solo")]
        )
        self.assertTrue(sprint_status.in_progress_is_teammate_data(teammate))
        self.assertFalse(sprint_status.in_progress_is_teammate_data(solo))


class TestSelectPromotedTeammateStories(_SMMTestCase):
    """The single home for "in-progress AND execution_mode == teammate".

    Two Python call sites needed that pair of literals — the boolean here, and
    the assign gate's predicate in lead_gates, which needs the LIST rather than
    the `any` — and each had spelled it out by hand. Two hand-written copies of a
    filter is how they start answering the same question in different words (the
    standing Reuse concern). The SELECTOR is the shared thing; the boolean is
    derived from it.
    """

    def test_selects_only_promoted_teammate_stories(self):
        import sprint_status

        stories = [
            _make_story(
                id="story-001", status="in-progress", execution_mode="teammate"
            ),
            _make_story(id="story-002", status="in-progress", execution_mode="solo"),
            _make_story(id="story-003", status="reviewing", execution_mode="teammate"),
            _make_story(id="story-004", status="scheduled", execution_mode="teammate"),
            _make_story(id="story-005", status="in-progress"),  # unset mode
        ]
        selected = sprint_status.select_promoted_teammate_stories(stories)
        self.assertEqual([s["id"] for s in selected], ["story-001"])

    def test_the_boolean_is_derived_from_the_selector(self):
        """Not merely "both are correct" — the same code answers both, so they
        cannot drift apart. A re-derived second copy of the filter is exactly
        what this consolidation removes."""
        import sprint_status

        for stories in (
            [_make_story(status="in-progress", execution_mode="teammate")],
            [_make_story(status="in-progress", execution_mode="solo")],
            [_make_story(status="reviewing", execution_mode="teammate")],
            [],
        ):
            with self.subTest(stories=stories):
                self.assertEqual(
                    sprint_status.in_progress_is_teammate_data({"stories": stories}),
                    bool(sprint_status.select_promoted_teammate_stories(stories)),
                )


if __name__ == "__main__":
    unittest.main()
