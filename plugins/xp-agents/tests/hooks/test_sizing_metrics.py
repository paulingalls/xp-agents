#!/usr/bin/env python3
"""Tests for sizing_metrics.py — commit-to-story attribution and sizing."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _s, _sprint_json, make_event


def _commit_event(
    files: list[str],
    ts: str = "2026-04-05T10:00:00+00:00",
    story_id: str | None = None,
) -> dict:
    metadata: dict = {"code_commit": True, "commit_hash": "abc123"}
    if story_id:
        metadata["story_id"] = story_id
    return make_event(
        "commit",
        content="Committed: test change",
        files=files,
        ts=ts,
        metadata=metadata,
    )


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


# ===========================================================================
# extract_file_domain_paths
# ===========================================================================


class TestExtractFileDomainPaths(unittest.TestCase):
    def test_extracts_path_before_dash(self):
        import sizing_metrics

        paths = sizing_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "tests/test_auth.py \u2014 auth tests"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "tests/test_auth.py"})

    def test_plain_path_without_description(self):
        import sizing_metrics

        paths = sizing_metrics.extract_file_domain_paths(["scripts/auth.py"])
        self.assertEqual(paths, {"scripts/auth.py"})

    def test_empty_list(self):
        import sizing_metrics

        paths = sizing_metrics.extract_file_domain_paths([])
        self.assertEqual(paths, set())

    def test_mixed_formats(self):
        import sizing_metrics

        paths = sizing_metrics.extract_file_domain_paths(
            ["scripts/auth.py \u2014 add login", "scripts/plain.py"]
        )
        self.assertEqual(paths, {"scripts/auth.py", "scripts/plain.py"})


# ===========================================================================
# _attribute_commits
# ===========================================================================


class TestAttributeCommits(unittest.TestCase):
    def test_single_commit_single_story(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["in_domain_files"], 1)
        self.assertEqual(result["story-001"]["out_of_domain_files"], 1)

    def test_story_id_determines_attribution(self):
        """story_id determines attribution, not file overlap."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
            _s(
                "story-002",
                "Tests",
                "S",
                "done",
                file_domain=["scripts/auth.py \u2014 update"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-002"]["commits"], 0)

    def test_no_story_id_not_attributed(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [_commit_event(["scripts/auth.py"])]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 0)
        self.assertEqual(result["story-001"]["files_changed"], 0)

    def test_domain_accuracy(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            _commit_event(
                [
                    "scripts/auth.py",
                    "scripts/x.py",
                    "scripts/y.py",
                    "scripts/z.py",
                ],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertAlmostEqual(
            result["story-001"]["domain_accuracy"],
            0.25,
        )

    def test_no_file_domain(self):
        import sizing_metrics

        stories = [
            _s("story-001", "Auth", "M", "done", file_domain=[]),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["in_domain_files"], 0)

    def test_test_file_matches_source_domain(self):
        """tests/hooks/test_foo.py should match domain scripts/foo.py."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=[
                    "scripts/retro_flags.py \u2014 add suppression",
                ],
            ),
        ]
        commits = [
            _commit_event(
                [
                    "scripts/retro_flags.py",
                    "tests/hooks/test_retro_flags.py",
                ],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["in_domain_files"], 2)

    def test_prefixed_path_matches_domain(self):
        """plugins/xp-agents/scripts/foo.py matches scripts/foo.py."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            _commit_event(
                ["plugins/xp-agents/scripts/auth.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["in_domain_files"], 1)

    def test_multiple_commits_deduped(self):
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 add login"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
            _commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
            ),
            _commit_event(["scripts/unrelated.py"]),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)

        self.assertEqual(result["story-001"]["commits"], 2)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["in_domain_files"], 1)
        self.assertEqual(result["story-001"]["out_of_domain_files"], 1)


# ===========================================================================
# _attribute_commits with metadata.story_id
# ===========================================================================


class TestAttributeCommitsStoryId(unittest.TestCase):
    """_attribute_commits uses metadata.story_id for attribution."""

    def test_story_id_attributes_to_correct_story(self):
        """Commit with story_id attributed only to that story."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 login"],
            ),
            _s(
                "story-002",
                "Tests",
                "S",
                "done",
                file_domain=["tests/test_auth.py \u2014 tests"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-002",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-002"]["commits"], 1)
        self.assertEqual(result["story-001"]["commits"], 0)

    def test_no_story_id_not_attributed(self):
        """Commit without story_id is not attributed to any story."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 login"],
            ),
        ]
        commits = [_commit_event(["scripts/auth.py"])]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 0)

    def test_unknown_story_id_not_attributed(self):
        """Commit with unknown story_id is not attributed."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 login"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-999",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 0)

    def test_file_dedup_across_commits(self):
        """Same file in 2 commits counted once in files_changed."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["scripts/auth.py \u2014 login"],
            ),
        ]
        commits = [
            _commit_event(
                ["scripts/auth.py"],
                story_id="story-001",
            ),
            _commit_event(
                ["scripts/auth.py", "scripts/util.py"],
                story_id="story-001",
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 2)
        self.assertEqual(result["story-001"]["files_changed"], 2)
        self.assertEqual(result["story-001"]["in_domain_files"], 1)

    def test_cross_cutting_commit_not_attributed_without_story_id(
        self,
    ):
        """Infrastructure commit without story_id doesn't pollute."""
        import sizing_metrics

        stories = [
            _s(
                "story-001",
                "Auth",
                "M",
                "done",
                file_domain=["CLAUDE.md \u2014 docs"],
            ),
        ]
        commits = [
            _commit_event(
                ["CLAUDE.md"],
                story_id="story-001",
            ),
            _commit_event(
                [
                    "CLAUDE.md",
                    "README.md",
                    "scripts/spawn.py",
                    "tests/test_spawn.py",
                ],
            ),
        ]
        result = sizing_metrics._attribute_commits(commits, stories)
        self.assertEqual(result["story-001"]["commits"], 1)
        self.assertEqual(result["story-001"]["files_changed"], 1)
        self.assertAlmostEqual(
            result["story-001"]["domain_accuracy"],
            1.0,
        )


# ===========================================================================
# _per_size_aggregates
# ===========================================================================


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
                "in_domain_files": 8,
                "out_of_domain_files": 2,
                "domain_accuracy": 0.8,
            },
            "story-002": {
                "commits": 2,
                "files_changed": 3,
                "in_domain_files": 3,
                "out_of_domain_files": 0,
                "domain_accuracy": 1.0,
            },
            "story-003": {
                "commits": 1,
                "files_changed": 5,
                "in_domain_files": 4,
                "out_of_domain_files": 1,
                "domain_accuracy": 0.8,
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
                "in_domain_files": 4,
                "out_of_domain_files": 1,
                "domain_accuracy": 0.8,
            },
        }
        result = sizing_metrics._per_size_aggregates(metrics, stories)

        self.assertIn("M", result)
        self.assertNotIn("S", result)
        self.assertNotIn("L", result)


# ===========================================================================
# compute_sizing_analysis (integration)
# ===========================================================================


class TestComputeSizingAnalysis(_HookTestCase):
    def test_full_sizing_analysis(self):
        import sizing_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            _commit_event(
                ["scripts/auth.py", "scripts/session.py"],
                "2026-04-02T10:00:00+00:00",
                story_id="story-001",
            ),
            _commit_event(
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
        self.assertEqual(story_001["in_domain_files"], 2)

        story_002 = next(s for s in result["per_story"] if s["id"] == "story-002")
        self.assertEqual(story_002["commits"], 1)

    def test_commit_before_sprint_excluded(self):
        import sizing_metrics

        (self.smm_dir / "sprint.json").write_text(SPRINT_WITH_DOMAINS)
        events = [
            _commit_event(
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
            _commit_event(
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
                        _commit_event(
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


if __name__ == "__main__":
    unittest.main()
