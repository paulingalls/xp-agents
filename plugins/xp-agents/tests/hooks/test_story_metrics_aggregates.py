#!/usr/bin/env python3
"""Tests for story_metrics.py — full analysis and per-agent aggregates."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _s, _sprint_json, commit_event, make_event
from event_schema import EVENT_TYPE_STATUS

SPRINT_WITH_DOMAINS = _sprint_json(
    [
        _s(
            "story-001",
            "Add auth",
            "done",
            file_domain=[
                "scripts/auth.py — add login",
                "scripts/session.py — token mgmt",
            ],
        ),
        _s(
            "story-002",
            "Add tests",
            "done",
            file_domain=["tests/test_auth.py — auth tests"],
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
    goal="Build auth system",
)


class TestComputeSizingAnalysis(_HookTestCase):
    def test_full_sizing_analysis(self):
        import story_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py", "scripts/session.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
            commit_event(
                ["tests/test_auth.py"],
                "2026-04-03T10:00:00+00:00",
                story_id="story-002",
            ),
        ]

        result = story_metrics.compute_story_analysis(
            self.smm_dir,
            events,
        )

        assert result is not None
        self.assertEqual(result["sprint_id"], "sprint-001")
        self.assertEqual(result["goal"], "Build auth system")
        self.assertEqual(
            result["velocity"]["stories_delivered"],
            2,
        )
        self.assertEqual(len(result["per_story"]), 2)

        story_001 = next(s for s in result["per_story"] if s["id"] == "story-001")
        self.assertEqual(story_001["commits"], 1)
        self.assertEqual(story_001["cascade_size"], 0)

        story_002 = next(s for s in result["per_story"] if s["id"] == "story-002")
        self.assertEqual(story_002["commits"], 1)

    def test_commit_before_sprint_excluded(self):
        import story_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-03-15T10:00:00+00:00",
                story_id="story-001",
            ),
        ]

        result = story_metrics.compute_story_analysis(
            self.smm_dir,
            events,
        )
        assert result is not None
        story_001 = next(s for s in result["per_story"] if s["id"] == "story-001")
        self.assertEqual(story_001["commits"], 0)

    def test_no_sprint_returns_none(self):
        import story_metrics

        result = story_metrics.compute_story_analysis(self.smm_dir, [])
        self.assertIsNone(result)

    def test_per_story_has_no_size_field(self):
        import story_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
        ]

        result = story_metrics.compute_story_analysis(
            self.smm_dir,
            events,
        )
        assert result is not None
        self.assertNotIn("per_size", result)
        for story in result["per_story"]:
            self.assertNotIn("size", story)

    def test_attribution_anomaly_truth_table(self):
        """attribution_anomaly is True iff status=deferred AND commits>0."""
        import story_metrics

        cases = [
            ("deferred", True, True),
            ("deferred", False, False),
            ("done", True, False),
            ("ready", True, False),
        ]
        for status, has_commits, expected in cases:
            with self.subTest(status=status, has_commits=has_commits):
                sprint = _sprint_json(
                    [
                        _s(
                            "story-x",
                            "Story",
                            status,
                            file_domain=["scripts/a.py"],
                        ),
                    ],
                    sprint_id="sprint-anom",
                    started="2026-04-01",
                )
                (self.smm_dir / "sprint.json").write_text(sprint)
                events = (
                    [
                        commit_event(
                            ["scripts/a.py"],
                            "2026-04-02T10:00:00+00:00",
                            story_id="story-x",
                        ),
                    ]
                    if has_commits
                    else []
                )

                result = story_metrics.compute_story_analysis(self.smm_dir, events)
                assert result is not None
                self.assertIs(result["per_story"][0]["attribution_anomaly"], expected)


class TestPerAgentAggregates(_HookTestCase):
    """Per-teammate windowing: max_events_to_commit uses per-agent scoping."""

    def test_parallel_teammates_per_agent_max_events(self):
        """3 teammates x 30 events each: per_agent max=30, not aggregate 90.

        story-010 examined this pin deliberately and KEPT 30 — the plan
        expected it to break, and it does not. The reason is that all 30
        events are code edits by the agent's own id: the first anchors the
        interval, the other 29 count, none are test telemetry, and the
        agent's own commit closes it. So the fixture is a well-formed batch
        under both the old and the new definition and 30 is right for a new
        reason. Changing the fixture to make it break would have been
        theatre, not a re-pin. See decision 256b7457b8ab.
        """
        import story_metrics

        sprint = _sprint_json(
            [
                _s("story-001", "Auth", "done", file_domain=["a.py"]),
                _s("story-002", "Tests", "done", file_domain=["b.py"]),
                _s("story-003", "Docs", "done", file_domain=["c.py"]),
            ],
            sprint_id="sprint-t",
            started="2026-04-01",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)

        events = []
        for agent_id, story_id, fpath in [
            ("teammate-1", "story-001", "a.py"),
            ("teammate-2", "story-002", "b.py"),
            ("teammate-3", "story-003", "c.py"),
        ]:
            for i in range(30):
                events.append(
                    make_event(
                        EVENT_TYPE_STATUS,
                        content=f"Working {i}",
                        working_on=[fpath],
                        agent_id=agent_id,
                        ts=f"2026-04-02T{10 + i // 60:02d}:{i % 60:02d}:00+00:00",
                    )
                )
            events.append(
                commit_event(
                    [fpath],
                    ts="2026-04-02T11:00:00+00:00",
                    story_id=story_id,
                )
            )
            events[-1]["agent_id"] = agent_id

        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        self.assertIn("per_agent", result)
        pa = result["per_agent"]
        self.assertEqual(len(pa), 3)
        for agent_id in ["teammate-1", "teammate-2", "teammate-3"]:
            self.assertIn(agent_id, pa)
            self.assertEqual(pa[agent_id]["max_events_to_commit"], 30)

    def _one_story_sprint(self):
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Auth", "done", file_domain=["a.py"])],
                sprint_id="sprint-t",
                started="2026-04-01",
            )
        )

    @staticmethod
    def _at(i):
        return f"2026-04-02T10:{i % 60:02d}:00+00:00"

    def _status(self, agent_id, i, **kwargs):
        kwargs.setdefault("working_on", [])
        return make_event(
            EVENT_TYPE_STATUS,
            content=f"event {i}",
            agent_id=agent_id,
            ts=self._at(i),
            **kwargs,
        )

    def _commit(self, agent_id):
        e = commit_event(["a.py"], ts=self._at(59), story_id="story-001")
        e["agent_id"] = agent_id
        return e

    def test_agent_without_commits_emits_no_batch_metric(self):
        """A reviewer cannot commit by design, so it has no batch interval.

        Reporting zero would be a different claim ("it committed, with an
        empty batch") — and reporting its raw event count, as before, let
        agents that never commit dominate the metric.
        """
        import story_metrics

        self._one_story_sprint()
        events = [
            self._status("teammate-1", 0, working_on=["a.py"]),
            self._commit("teammate-1"),
            *[
                self._status("xp-plan-reviewer", i, working_on=["a.py"])
                for i in range(40)
            ],
        ]

        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        pa = result["per_agent"]
        self.assertIn("teammate-1", pa)
        self.assertNotIn("xp-plan-reviewer", pa)

    def test_events_before_first_edit_do_not_count(self):
        """Anchor at the first code edit — planning is not batching."""
        import story_metrics

        self._one_story_sprint()
        events = [
            *[
                make_event(content=f"talk {i}", agent_id="teammate-1", ts=self._at(i))
                for i in range(10)
            ],
            self._status("teammate-1", 10, working_on=["a.py"]),
            self._commit("teammate-1"),
        ]

        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        self.assertEqual(result["per_agent"]["teammate-1"]["max_events_to_commit"], 1)

    def test_test_runs_excluded_from_the_prose_counter_too(self):
        """Interface contract: same key, same exclusions, both producers."""
        import story_metrics

        self._one_story_sprint()
        events = [
            self._status("teammate-1", 0, working_on=["a.py"]),
            *[
                self._status("teammate-1", i, metadata={"action": "test_run_complete"})
                for i in range(1, 6)
            ],
            self._commit("teammate-1"),
        ]

        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        self.assertEqual(result["per_agent"]["teammate-1"]["max_events_to_commit"], 1)

    def test_both_producers_agree_on_the_same_stream(self):
        """`max_events_to_commit` must mean one thing, not two.

        This story exists because two modules produced the same key with
        different meanings. This pin fails the moment they diverge again.
        """
        import story_metrics
        import work_signals

        self._one_story_sprint()
        events = [
            *[
                make_event(content=f"talk {i}", agent_id="teammate-1", ts=self._at(i))
                for i in range(3)
            ],
            *[self._status("teammate-1", i, working_on=["a.py"]) for i in range(3, 12)],
            self._status("teammate-1", 12, metadata={"action": "test_run_complete"}),
            self._commit("teammate-1"),
        ]

        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        flag = work_signals.build_work_signals(events)
        self.assertEqual(
            result["per_agent"]["teammate-1"]["max_events_to_commit"],
            flag["max_events_to_commit"],
        )
        self.assertEqual(flag["max_events_to_commit"], 9)

    def test_compute_story_analysis_gains_per_agent_key(self):
        """compute_story_analysis return shape gains per_agent dict."""
        import story_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
        ]
        result = story_metrics.compute_story_analysis(self.smm_dir, events)
        assert result is not None
        self.assertIn("per_agent", result)
        self.assertIsInstance(result["per_agent"], dict)


if __name__ == "__main__":
    unittest.main()
