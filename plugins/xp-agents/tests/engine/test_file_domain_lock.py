#!/usr/bin/env python3
"""Tests for file_domain_lock.py's pure collision detector and formatter.

TDD order: collision_report behaviors, then format_collision_report, then
one on-disk E2E case. No caller is wired in this story — see the module
docstring for why.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import file_domain_lock
import sprint_store
from conftest import _SMMTestCase, make_sprint_dict, make_story_dict


class TestCollisionReport(unittest.TestCase):
    def test_disjoint_domains_yield_empty_report(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["a.py — module a"]),
                make_story_dict(id="story-002", file_domain=["b.py — module b"]),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_shared_literal_path_maps_to_both_story_ids(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report,
            {
                "shared.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "authored"},
                ]
            },
        )

    def test_marked_claim_is_auto_included_unmarked_is_authored(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — authored"]),
                make_story_dict(
                    id="story-002",
                    file_domain=["shared.py — sister test for src.py"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report,
            {
                "shared.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "auto_included"},
                ]
            },
        )

    def test_comma_joined_entry_attributes_each_path_separately(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001", file_domain=["a.py, b.py — two modules"]
                ),
                make_story_dict(id="story-002", file_domain=["b.py — b again"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(list(report.keys()), ["b.py"])
        for path_list in report.values():
            for owner in path_list:
                self.assertNotIn("two modules", owner["story_id"])
        self.assertNotIn("a.py", report)
        self.assertNotIn("two modules", report)

    def test_same_story_declaring_path_twice_is_not_a_collision(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=["shared.py — first", "shared.py — again"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_empty_file_domain_never_appears(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=[]),
                make_story_dict(id="story-002", file_domain=["a.py — a"]),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_non_str_entries_skipped(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=[123, {"x": 1}]),
                make_story_dict(id="story-002", file_domain=["a.py — a"]),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_glob_tokens_compared_literally(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["src/*.py — glob"]),
                make_story_dict(id="story-002", file_domain=["src/*.py — glob too"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report,
            {
                "src/*.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "authored"},
                ]
            },
        )

    def test_path_claimed_by_three_stories(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
                make_story_dict(id="story-003", file_domain=["shared.py — c"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report["shared.py"],
            [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-002", "origin": "authored"},
                {"story_id": "story-003", "origin": "authored"},
            ],
        )

    def test_both_stories_sister_marked_same_path(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=["shared.py — sister test for a.py"],
                ),
                make_story_dict(
                    id="story-002",
                    file_domain=["shared.py — sister test for b.py"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report,
            {
                "shared.py": [
                    {"story_id": "story-001", "origin": "auto_included"},
                    {"story_id": "story-002", "origin": "auto_included"},
                ]
            },
        )

    def test_authored_wins_over_auto_included_within_story(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=[
                        "shared.py — authored explicitly",
                        "shared.py — sister test for a.py",
                    ],
                ),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report["shared.py"],
            [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-002", "origin": "authored"},
            ],
        )

    def test_authored_wins_when_auto_included_declared_first(self):
        # Reverse-order sibling of the test above: the sister-test entry
        # precedes the authored one, so authored must UPGRADE the origin
        # (exercises the overwrite branch, not the early-continue branch).
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=[
                        "shared.py — sister test for a.py",
                        "shared.py — authored explicitly",
                    ],
                ),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report["shared.py"],
            [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-002", "origin": "authored"},
            ],
        )

    def test_story_with_non_str_id_is_skipped(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id=123, file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        # The 123-id story is dropped entirely, leaving one owner -> no
        # collision. Guards against a non-str id ever landing in a report.
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_duplicate_story_id_same_path_is_reported(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-001", file_domain=["shared.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            report["shared.py"],
            [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-001", "origin": "authored"},
            ],
        )

    def test_report_is_deterministic(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-003", file_domain=["z.py — a", "a.py — a"]),
                make_story_dict(id="story-001", file_domain=["z.py — b", "a.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(list(report.keys()), ["a.py", "z.py"])
        for owners in report.values():
            self.assertEqual(
                owners, sorted(owners, key=lambda o: (o["story_id"], o["origin"]))
            )


class TestFormatCollisionReport(unittest.TestCase):
    def test_format_empty_report_returns_empty_string(self):
        self.assertEqual(file_domain_lock.format_collision_report({}), "")

    def test_format_names_every_colliding_path_with_owners_and_origins(self):
        report = {
            "a.py": [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-002", "origin": "authored"},
            ],
            "b.py": [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-003", "origin": "auto_included"},
            ],
        }
        message = file_domain_lock.format_collision_report(report)
        self.assertIn("a.py", message)
        self.assertIn("b.py", message)
        self.assertIn("story-001", message)
        self.assertIn("story-002", message)
        self.assertIn("story-003", message)

    def test_format_distinguishes_authored_and_auto_included(self):
        report = {
            "a.py": [
                {"story_id": "story-001", "origin": "authored"},
                {"story_id": "story-002", "origin": "auto_included"},
            ],
        }
        message = file_domain_lock.format_collision_report(report)
        self.assertIn("authored", message)
        self.assertIn("auto_included", message)
        self.assertIn("planner error", message)
        self.assertIn("tool error", message)


class TestDependencyAwareCollisionRule(unittest.TestCase):
    """A path may be shared by stories that can never run concurrently.

    Exclusivity exists to keep parallel teammates off each other's files, not
    to stop a story from building on an earlier one. Two stories can never run
    concurrently when one transitively depends on the other, or when either has
    reached a terminal status (done/deferred) and released its files.
    """

    def test_dependent_story_may_share_a_path_with_its_dependency(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(
                    id="story-002",
                    dependencies=["story-001"],
                    file_domain=["shared.py — extend it"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_transitive_dependency_may_share_a_path(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", dependencies=["story-001"]),
                make_story_dict(
                    id="story-003",
                    dependencies=["story-002"],
                    file_domain=["shared.py — extend it again"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_independent_stories_sharing_a_path_still_collide(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            sorted(c["story_id"] for c in report["shared.py"]),
            ["story-001", "story-002"],
        )

    def test_done_story_releases_its_paths(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="done",
                    file_domain=["shared.py — merged already"],
                ),
                make_story_dict(
                    id="story-002", file_domain=["shared.py — build on it"]
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_deferred_story_releases_its_paths(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="deferred",
                    file_domain=["shared.py — punted"],
                ),
                make_story_dict(id="story-002", file_domain=["shared.py — take it"]),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_only_the_concurrent_pair_is_reported(self):
        """story-003 depends on story-001, so that pair is legal; story-002 is
        independent of both, so it collides with each."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
                make_story_dict(
                    id="story-003",
                    dependencies=["story-001"],
                    file_domain=["shared.py — c"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            sorted(c["story_id"] for c in report["shared.py"]),
            ["story-001", "story-002", "story-003"],
        )

    def test_dependency_cycle_does_not_hang_and_reports_nothing(self):
        """A malformed dependency cycle must terminate. Each is an ancestor of
        the other, so neither can be a concurrent claimant."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    dependencies=["story-002"],
                    file_domain=["shared.py — a"],
                ),
                make_story_dict(
                    id="story-002",
                    dependencies=["story-001"],
                    file_domain=["shared.py — b"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_non_dict_story_is_skipped_without_raising(self):
        """_cmd_add_story appends whatever JSON it was handed; a malformed
        payload must fall through to the schema validator, not AttributeError."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                ["not", "a", "story"],
                "neither is this",
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})


class TestFileDomainLockE2E(_SMMTestCase):
    def test_e2e_sprint_json_on_disk_shared_authored_path(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["shared.py — a"]),
                make_story_dict(id="story-002", file_domain=["shared.py — b"]),
            ]
        )
        sprint_store.save_sprint(self.smm_dir, data)
        loaded = sprint_store.load_sprint_required(self.smm_dir)
        report = file_domain_lock.collision_report(loaded)
        self.assertEqual(
            report,
            {
                "shared.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "authored"},
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
