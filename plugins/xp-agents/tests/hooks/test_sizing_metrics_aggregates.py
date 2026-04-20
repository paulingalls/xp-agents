#!/usr/bin/env python3
"""Tests for sizing_metrics.py — per-size aggregates and full analysis."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _s, _sprint_json, commit_event, make_event

SPRINT_WITH_DOMAINS = _sprint_json(
    [
        _s(
            "story-001",
            "Add auth",
            "M",
            "done",
            file_domain=[
                "scripts/auth.py \u2014 add login",
                "scripts/session.py \u2014 token mgmt",
            ],
        ),
        _s(
            "story-002",
            "Add tests",
            "S",
            "done",
            file_domain=["tests/test_auth.py \u2014 auth tests"],
        ),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
    goal="Build auth system",
)


class TestPerSizeAggregates(unittest.TestCase):
    def test_basic_aggregation(self):
        import sizing_metrics

        stories = [
            {"id": "story-001", "size": "M", "title": "A", "status": "done"},
            {"id": "story-002", "size": "S", "title": "B", "status": "done"},
            {"id": "story-003", "size": "S", "title": "C", "status": "done"},
        ]
        metrics = {
            "story-001": {
                "commits": 4,
                "files_changed": 10,
                "cascade_size": 2,
            },
            "story-002": {
                "commits": 2,
                "files_changed": 3,
                "cascade_size": 0,
            },
            "story-003": {
                "commits": 1,
                "files_changed": 5,
                "cascade_size": 1,
            },
        }
        result = sizing_metrics._per_size_aggregates(metrics, stories)

        self.assertEqual(result["M"]["count"], 1)
        self.assertAlmostEqual(result["M"]["avg_commits"], 4.0)
        self.assertAlmostEqual(result["M"]["avg_files"], 10.0)
        self.assertEqual(result["S"]["count"], 2)
        self.assertAlmostEqual(result["S"]["avg_commits"], 1.5)
        self.assertAlmostEqual(result["S"]["avg_files"], 4.0)

    def test_empty_size_category_excluded(self):
        import sizing_metrics

        stories = [
            {"id": "story-001", "size": "M", "title": "A", "status": "done"},
        ]
        metrics = {
            "story-001": {
                "commits": 2,
                "files_changed": 5,
                "cascade_size": 1,
            },
        }
        result = sizing_metrics._per_size_aggregates(metrics, stories)

        self.assertIn("M", result)
        self.assertNotIn("S", result)
        self.assertNotIn("L", result)


class TestComputeSizingAnalysis(_HookTestCase):
    def test_full_sizing_analysis(self):
        import sizing_metrics

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

        result = sizing_metrics.compute_sizing_analysis(
            self.smm_dir,
            events,
        )

        self.assertIsNotNone(result)
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
        import sizing_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-03-15T10:00:00+00:00",
                story_id="story-001",
            ),
        ]

        result = sizing_metrics.compute_sizing_analysis(
            self.smm_dir,
            events,
        )
        story_001 = next(s for s in result["per_story"] if s["id"] == "story-001")
        self.assertEqual(story_001["commits"], 0)

    def test_no_sprint_returns_none(self):
        import sizing_metrics

        result = sizing_metrics.compute_sizing_analysis(self.smm_dir, [])
        self.assertIsNone(result)

    def test_per_size_present(self):
        import sizing_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
        ]

        result = sizing_metrics.compute_sizing_analysis(
            self.smm_dir,
            events,
        )
        self.assertIn("per_size", result)
        self.assertIn("M", result["per_size"])

    def test_attribution_anomaly_truth_table(self):
        """attribution_anomaly is True iff status=deferred AND commits>0."""
        import sizing_metrics

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
                            "M",
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

                result = sizing_metrics.compute_sizing_analysis(self.smm_dir, events)
                self.assertIs(result["per_story"][0]["attribution_anomaly"], expected)


class TestPerAgentAggregates(_HookTestCase):
    """Per-teammate windowing: max_events_to_commit uses per-agent scoping."""

    def test_parallel_teammates_per_agent_max_events(self):
        """3 teammates x 30 events each: per_agent max=30, not aggregate 90."""
        import sizing_metrics

        sprint = _sprint_json(
            [
                _s("story-001", "Auth", "M", "done", file_domain=["a.py"]),
                _s("story-002", "Tests", "S", "done", file_domain=["b.py"]),
                _s("story-003", "Docs", "S", "done", file_domain=["c.py"]),
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
                        "status",
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

        result = sizing_metrics.compute_sizing_analysis(self.smm_dir, events)
        self.assertIn("per_agent", result)
        pa = result["per_agent"]
        self.assertEqual(len(pa), 3)
        for agent_id in ["teammate-1", "teammate-2", "teammate-3"]:
            self.assertIn(agent_id, pa)
            self.assertEqual(pa[agent_id]["max_events_to_commit"], 30)

    def test_compute_sizing_analysis_gains_per_agent_key(self):
        """compute_sizing_analysis return shape gains per_agent dict."""
        import sizing_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            commit_event(
                ["scripts/auth.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
        ]
        result = sizing_metrics.compute_sizing_analysis(self.smm_dir, events)
        self.assertIn("per_agent", result)
        self.assertIsInstance(result["per_agent"], dict)


if __name__ == "__main__":
    unittest.main()
