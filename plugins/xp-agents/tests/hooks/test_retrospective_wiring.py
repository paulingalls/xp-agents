#!/usr/bin/env python3
"""Tests for retrospective decision wiring and try resolution.

Split from test_retrospective.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event, make_milestone_dict, make_plan_dict
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_RETROSPECTIVE,
    EVENT_TYPE_STATUS,
)


class TestDecisionTopicsWiring(_HookTestCase):
    """evaluate_flags receives decision topics extracted from events."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_decision_topics_suppress_flags(self):
        import retrospective

        decision = make_event(
            EVENT_TYPE_DECISION,
            content="Adopted retro Try: kickoff exemption",
            topic="retro-try-kickoff-exemption",
        )
        code_event = make_event(
            EVENT_TYPE_STATUS, content="wrote code", working_on=["foo.py"]
        )
        filler = [make_event(content=f"f{i}") for i in range(80)]
        commit = make_event(EVENT_TYPE_COMMIT, content="git commit")
        events = [decision, code_event, *filler, commit]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        flag_metrics = [f["metric"] for f in data["digest"]["flags"]]
        self.assertNotIn("max_events_to_commit", flag_metrics)

    def test_no_decision_topics_flags_fire(self):
        import retrospective

        code_event = make_event(
            EVENT_TYPE_STATUS, content="wrote code", working_on=["foo.py"]
        )
        filler = [make_event(content=f"f{i}") for i in range(80)]
        commit = make_event(EVENT_TYPE_COMMIT, content="git commit")
        events = [code_event, *filler, commit]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        flag_metrics = [f["metric"] for f in data["digest"]["flags"]]
        self.assertIn("max_events_to_commit", flag_metrics)


class TestDroppedTryResolution(_HookTestCase):
    """Dropped Try items should be detected across session boundaries
    and preserved in previous_retros[0].try with disposition="dropped",
    so the retro agent's no-re-propose rule at xp-retrospective.md:208
    is reachable.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_dropped_try_preserved_across_session_boundary(self):
        import retrospective

        old_concern_id = "aabb11223344"
        old_concern = make_event(
            EVENT_TYPE_CONCERN,
            id=old_concern_id,
            content="Test coverage gap",
            severity="medium",
        )
        retro_event = make_event(
            EVENT_TYPE_RETROSPECTIVE,
            content="Session retro: 3 keeps, 2 fixes, 1 try",
            keep=[{"content": "Good work", "event_refs": []}],
            fix=[],
            **{
                "try": [
                    {
                        "content": "Fix coverage",
                        "event_refs": [old_concern_id],
                    }
                ]
            },
        )
        retro_json = {
            "timestamp": "2026-04-19T00:00:00+00:00",
            "keep": [{"content": "Good work", "event_refs": []}],
            "fix": [],
            "try": [
                {
                    "content": "Fix coverage",
                    "event_refs": [old_concern_id],
                }
            ],
        }
        retro_file = self.smm_dir / "retrospectives" / "2026-04-19T00-00-00.json"
        retro_file.write_text(json.dumps(retro_json))

        drop_event = make_event(
            EVENT_TYPE_STATUS,
            content="Fix coverage",
            working_on=[],
            metadata={
                "resolves": [old_concern_id],
                "disposition": "dropped",
            },
        )
        new_events = [make_event(content=f"work {i}") for i in range(5)]

        self._write_events([old_concern, retro_event, drop_event, *new_events])
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        prev = data.get("previous_retros", [])
        self.assertTrue(len(prev) > 0)
        # Dropped Try preserved with disposition recorded — strip-then-
        # silently-lose semantics has been removed (see retro_history.py).
        self.assertEqual(len(prev[0].get("try", [])), 1)
        statuses = prev[0].get("try_status", [])
        self.assertEqual(len(statuses), 1)
        self.assertTrue(statuses[0]["resolved_this_session"])
        self.assertEqual(statuses[0]["disposition"], "dropped")


class TestPlanSchedule(_HookTestCase):
    """`plan_schedule` maps a recorded item's id to the milestone that schedules
    it, so the retro agent can tell "already scheduled" from "unresolved xN".

    The status filter is the whole story in miniature. Milestone status is one of
    {planned, in-progress, delivered, deferred}, so the tempting `!= "delivered"`
    filter ADMITS `deferred` — and a deferred milestone schedules nothing. The
    retro would report an aging debt as "scheduled in M5" and quietly stop
    escalating work nobody will do: the same false reassurance, mirrored.
    Excluding `delivered` kills the other trap — a milestone that already SHIPPED
    without fixing the debt is not going to fix it. Both fall out of reusing
    `execution_plan_store.ACTIVE_MILESTONE_STATUSES`, the set `plan_is_complete`
    already means by "still owes work"; a second hand-written status list here
    would be free to drift from it.

    Keyed by ID, not by the digest's signal_events: three of the four nags that
    motivated this arose from the model recalling an id from a previous retro's
    prose, the event itself long since compacted out of the live log. A map that
    covered only ids present in the digest would miss exactly those.
    """

    DEBT_ID = "4ecd48c71327"

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def _run_with_plan(self, plan: dict | None) -> dict:
        """Run the retro builder over 5 filler events, with *plan* on disk (or
        no plan at all when None). Returns the parsed .retro-input.json."""
        import retrospective

        if plan is not None:
            (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self._write_events([make_event(content=f"work {i}") for i in range(5)])
        retrospective.run(
            {"session_id": "test", "source": "startup"}, smm_dir=self.smm_dir
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            return json.load(f)

    def _plan_with(self, status: str) -> dict:
        return make_plan_dict(
            milestones=[
                make_milestone_dict(
                    number=4,
                    name="Close gates honor evidence, not intent",
                    status=status,
                    delivered_sprint="sprint-117" if status == "delivered" else None,
                    schedules=[self.DEBT_ID],
                )
            ]
        )

    def test_planned_milestone_is_mapped(self):
        data = self._run_with_plan(self._plan_with("planned"))
        self.assertEqual(
            data["plan_schedule"],
            {self.DEBT_ID: "M4: Close gates honor evidence, not intent"},
        )

    def test_in_progress_milestone_is_mapped(self):
        data = self._run_with_plan(self._plan_with("in-progress"))
        self.assertEqual(
            data["plan_schedule"],
            {self.DEBT_ID: "M4: Close gates honor evidence, not intent"},
        )

    def test_delivered_milestone_is_omitted(self):
        """It already SHIPPED without fixing the debt — so it is not going to.
        Reporting it as scheduled would stop the escalation forever."""
        data = self._run_with_plan(self._plan_with("delivered"))
        self.assertEqual(data["plan_schedule"], {})

    def test_deferred_milestone_is_omitted(self):
        """A deferred milestone schedules NOTHING. This is the case a
        `!= "delivered"` filter would wrongly admit."""
        data = self._run_with_plan(self._plan_with("deferred"))
        self.assertEqual(data["plan_schedule"], {})

    def test_no_plan_degrades_to_empty_map(self):
        """load_plan returns None when absent — degrade, never raise."""
        data = self._run_with_plan(None)
        self.assertEqual(data["plan_schedule"], {})

    def test_corrupt_plan_degrades_to_empty_map(self):
        """A broken plan must not take SessionStart down with it.

        `load_plan` is fail-LOUD (ValueError on malformed JSON or a schema-
        invalid doc), and its other callers rightly let that raise — they are
        plan tools, and a plan tool on a corrupt plan has nothing to do. This
        caller is different in kind: `plan_schedule` ANNOTATES a retro the hook
        has already decided to run, and the retro ran fine before this field
        existed. Letting the plan's corruption abort the SessionStart hook would
        newly couple every session start to plan validity — and take out the
        retro that is the user's best channel for hearing about it.

        Degrading costs exactly the annotation: an empty map means "nothing
        known to be scheduled", which is the pre-story behaviour (the agent
        escalates), not a wrong answer. Same rationale, same shape as
        `intent.load_ledger`, which is fail-QUIET for this reason.
        """
        (self.smm_dir / "execution_plan.json").write_text("{ not json")
        self._write_events([make_event(content=f"work {i}") for i in range(5)])

        import retrospective

        retrospective.run(
            {"session_id": "test", "source": "startup"}, smm_dir=self.smm_dir
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            self.assertEqual(json.load(f)["plan_schedule"], {})

    def test_milestone_without_schedules_contributes_nothing(self):
        plan = make_plan_dict(milestones=[make_milestone_dict(status="planned")])
        self.assertNotIn("schedules", plan["milestones"][0])
        self.assertEqual(self._run_with_plan(plan)["plan_schedule"], {})

    def test_open_and_closed_milestones_together(self):
        """The open milestone's ids land; the delivered one's do not — even
        though both name a still-open debt."""
        other_id = "4cce3e34eafb"
        plan = make_plan_dict(
            milestones=[
                make_milestone_dict(
                    number=1,
                    name="Shipped already",
                    status="delivered",
                    delivered_sprint="sprint-110",
                    schedules=[other_id],
                ),
                make_milestone_dict(
                    number=4,
                    name="Close gates honor evidence, not intent",
                    status="in-progress",
                    schedules=[self.DEBT_ID],
                ),
            ]
        )
        self.assertEqual(
            self._run_with_plan(plan)["plan_schedule"],
            {self.DEBT_ID: "M4: Close gates honor evidence, not intent"},
        )

    def test_two_active_milestones_naming_one_debt_report_the_earlier(self):
        """A one-label map has to pick when two live milestones name the same
        debt. Pick the EARLIER one: it is the one the debt gets fixed by, and
        "scheduled in M2" is the answer that survives M4 being re-planned."""
        plan = make_plan_dict(
            milestones=[
                make_milestone_dict(
                    number=2,
                    name="Earlier",
                    status="in-progress",
                    schedules=[self.DEBT_ID],
                ),
                make_milestone_dict(
                    number=4,
                    name="Later",
                    status="planned",
                    schedules=[self.DEBT_ID],
                ),
            ]
        )
        self.assertEqual(
            self._run_with_plan(plan)["plan_schedule"],
            {self.DEBT_ID: "M2: Earlier"},
        )


if __name__ == "__main__":
    unittest.main()
