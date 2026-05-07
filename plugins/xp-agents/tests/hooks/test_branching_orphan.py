#!/usr/bin/env python3
"""Tests for orphan story-branch detection.

list_story_branches returns story branches owned by the current user.
list_orphan_story_branches cross-references with sprint.json to find
branches not backed by an active (ready/in-progress) story.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branch_queries
from conftest import _s, _sprint_json


def _create_branch(td: str, name: str) -> None:
    subprocess.run(
        ["git", "branch", name],
        cwd=td,
        capture_output=True,
        check=True,
        env=_bf.GIT_ENV,
    )


class TestListStoryBranches(unittest.TestCase):
    def test_no_story_branches(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = branch_queries.list_story_branches(td)
            self.assertEqual(result, [])

    def test_returns_story_branches(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _create_branch(td, "test/story-001-add-nudge")
            _create_branch(td, "test/story-002-fix-cascade")
            result = branch_queries.list_story_branches(td)
            self.assertEqual(len(result), 2)
            self.assertIn("test/story-001-add-nudge", result)
            self.assertIn("test/story-002-fix-cascade", result)

    def test_excludes_head(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _create_branch(td, "test/story-001-nudge")
            subprocess.run(
                ["git", "checkout", "test/story-001-nudge"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branch_queries.list_story_branches(td)
            self.assertEqual(result, [])

    def test_excludes_non_story_branches(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            _create_branch(td, "test/story-001-nudge")
            _create_branch(td, "test/sprint-047-reliability")
            _create_branch(td, "test/free-2026-04-29-test")
            result = branch_queries.list_story_branches(td)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0], "test/story-001-nudge")


class TestListOrphanStoryBranches(unittest.TestCase):
    def _write_sprint(self, smm_dir: Path, sprint_json_str: str) -> None:
        (smm_dir / "sprint.json").write_text(sprint_json_str)

    def test_no_sprint_all_orphans(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            _create_branch(td, "test/story-002-cascade")
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(len(result), 2)

    def test_in_progress_not_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "in-progress",
                            branch_name="test/story-001-nudge",
                        )
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, [])

    def test_reviewing_story_not_orphan(self):
        # A reviewing story is mid-acceptance — its branch is NOT orphan,
        # /xp-accept may still need it for tests / fix-cycles. Without
        # this widening, kickoff orphan-triage would offer to merge or
        # delete a story branch that's actively under review.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "reviewing",
                            branch_name="test/story-001-nudge",
                        )
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, [])

    def test_closing_story_not_orphan(self):
        # A closing story is mid-merge — its branch is intentionally alive
        # for /xp-story-close's merge into the sprint base. Without
        # widening the active set to include `closing`, kickoff
        # orphan-triage would offer to delete a branch the close skill is
        # actively merging.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            _create_branch(td, "test/story-999-unrelated")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "closing",
                            branch_name="test/story-001-nudge",
                        )
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, ["test/story-999-unrelated"])

    def test_all_in_motion_statuses_not_orphan(self):
        # Every active status (ready, in-progress, reviewing, closing)
        # must keep its branch out of the orphan list — these are the
        # statuses where the branch is legitimately alive.
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-ready")
            _create_branch(td, "test/story-002-progress")
            _create_branch(td, "test/story-003-review")
            _create_branch(td, "test/story-004-closing")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Ready",
                            "ready",
                            branch_name="test/story-001-ready",
                        ),
                        _s(
                            "story-002",
                            "In progress",
                            "in-progress",
                            branch_name="test/story-002-progress",
                        ),
                        _s(
                            "story-003",
                            "Reviewing",
                            "reviewing",
                            branch_name="test/story-003-review",
                        ),
                        _s(
                            "story-004",
                            "Closing",
                            "closing",
                            branch_name="test/story-004-closing",
                        ),
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, [])

    def test_done_story_is_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "done",
                            branch_name="test/story-001-nudge",
                        )
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(len(result), 1)
            self.assertIn("test/story-001-nudge", result)

    def test_ready_story_not_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "ready",
                            branch_name="test/story-001-nudge",
                        )
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, [])

    def test_no_story_branches_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(result, [])

    def test_mixed_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            smm_dir = Path(td) / "smm"
            smm_dir.mkdir()
            _create_branch(td, "test/story-001-nudge")
            _create_branch(td, "test/story-002-cascade")
            _create_branch(td, "test/story-003-orphan")
            self._write_sprint(
                smm_dir,
                _sprint_json(
                    [
                        _s(
                            "story-001",
                            "Add nudge",
                            "in-progress",
                            branch_name="test/story-001-nudge",
                        ),
                        _s(
                            "story-002",
                            "Add cascade",
                            "done",
                            branch_name="test/story-002-cascade",
                        ),
                        _s(
                            "story-003",
                            "Add orphan",
                            "deferred",
                            branch_name="test/story-003-orphan",
                        ),
                    ]
                ),
            )
            result = branch_queries.list_orphan_story_branches(td, smm_dir)
            self.assertEqual(len(result), 2)
            self.assertIn("test/story-002-cascade", result)
            self.assertIn("test/story-003-orphan", result)
            self.assertNotIn("test/story-001-nudge", result)


if __name__ == "__main__":
    unittest.main()
