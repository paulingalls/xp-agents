#!/usr/bin/env python3
"""create_story_branch writes the branch name BACK onto the story, and resumes it.

Split from `test_branching_story_creation.py` (500 lines). Creation and resume are
about git; these two classes are about the sprint RECORD: the created name is
persisted onto the story, and a later run resumes the recorded branch even after
the story has been retitled (concern f8043e9174a7) — which is the case a
title-derived name gets wrong.

Every test here seeds the SPRINT BRANCH, not just sprint.json. Seeding only the
record lets the story branch fork off whatever the base resolver degrades to,
which was primary — so the fixture would pass while proving the wrong thing.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching
import sprint_store

_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context


def _make_sprint_branch(td: str, name: str) -> None:
    """Cut the sprint branch the story base will resolve to.

    Without it, a seeded sprint at stage 2+ whose branch does not exist is the
    unresolvable state create_story_branch now refuses.
    """
    _bf.make_branch(td, name)


class TestCreateStoryBranchAutoRecords(unittest.TestCase):
    """Both tests seed the SPRINT BRANCH, not just sprint.json.

    They used to seed only the sprint record and let the story branch fork off
    whatever get_story_base_branch degraded to — which was primary. That is the
    exact dishonest state story-008 now refuses (a sprint exists at stage 2+,
    but its branch does not), so leaving them as they were would have meant
    asserting the auto-record behavior from inside the bug. Cutting the sprint
    branch makes the base resolvable, and the story branch now forks off the
    sprint branch, which is what production does.
    """

    def test_records_branch_name_in_sprint(self):
        import json

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_sprint_branch(td, "paul/sprint-044-test")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)
            sprint = {
                "sprint_id": "sprint-044",
                "goal": "test",
                "started": "2026-04-29",
                "stories": [
                    {
                        "id": "story-001",
                        "title": "Test",
                        "status": "in-progress",
                        "dependencies": [],
                        "milestone_ref": "",
                        "design_sources": "",
                        "context": "",
                        "file_domain": [],
                        "interface_contracts": [],
                        "acceptance_criteria": [],
                    }
                ],
            }
            (smm_dir / "sprint.json").write_text(json.dumps(sprint))

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "auto-record", smm_dir
                )

            self.assertEqual(result, "paul/story-001-auto-record")
            loaded = sprint_store.load_sprint(smm_dir)
            assert loaded is not None
            self.assertEqual(
                loaded["stories"][0].get("branch_name"),
                "paul/story-001-auto-record",
            )

    def test_missing_story_id_still_creates_branch(self):
        """Branch created even when story_id is absent from sprint.json."""
        import json

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_sprint_branch(td, "paul/sprint-044-test")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)
            sprint = {
                "sprint_id": "sprint-044",
                "goal": "test",
                "started": "2026-04-29",
                "stories": [
                    {
                        "id": "story-001",
                        "title": "Other",
                        "status": "in-progress",
                        "dependencies": [],
                        "milestone_ref": "",
                        "design_sources": "",
                        "context": "",
                        "file_domain": [],
                        "interface_contracts": [],
                        "acceptance_criteria": [],
                    }
                ],
            }
            (smm_dir / "sprint.json").write_text(json.dumps(sprint))

            with patch(
                "branching.identity.user_namespace",
                return_value="paul",
            ):
                result = branching.create_story_branch(
                    td, "story-999", "missing", smm_dir
                )

            self.assertEqual(result, "paul/story-999-missing")


class TestCreateStoryBranchResumesRecordedBranch(unittest.TestCase):
    """The story-branch leg of the reslice preserve (concern f8043e9174a7).

    create_sprint_branch already resumes the branch RECORDED for a sprint_id
    rather than rebuilding it from a (possibly rewritten) goal slug — see
    resolve_sprint_branch_name / _recorded_sprint_branch in
    branch_resolution.py. create_story_branch had no equivalent leg: it
    always rebuilt the branch name from the caller's slug. /xp-schedule and
    /xp-assign always pass a TITLE-derived slug (SKILL.md's
    `--slug <title-slug>`), so a re-slice that RETITLES a scheduled/ready
    story cuts a second, empty branch from the new title slug and strands
    the carried-forward branch as an orphan.
    """

    def test_resumes_recorded_branch_when_story_retitled(self):
        import json

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_sprint_branch(td, "paul/sprint-050-test")
            # The branch already cut (and recorded) under the story's
            # ORIGINAL title.
            subprocess.run(
                ["git", "branch", "paul/story-001-original-title"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)
            sprint = {
                "sprint_id": "sprint-050",
                "goal": "test",
                "started": "2026-04-29",
                "branch_name": "paul/sprint-050-test",
                "stories": [
                    {
                        "id": "story-001",
                        "title": "Retitled story",
                        "status": "scheduled",
                        "dependencies": [],
                        "milestone_ref": "",
                        "design_sources": "",
                        "context": "",
                        "file_domain": [],
                        "interface_contracts": [],
                        "acceptance_criteria": [],
                        "branch_name": "paul/story-001-original-title",
                    }
                ],
            }
            (smm_dir / "sprint.json").write_text(json.dumps(sprint))

            # The re-slice hands a NEW, title-derived slug for the same
            # story_id — exactly what SKILL.md's `--slug <title-slug>` does
            # after a retitle.
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "retitled-story", smm_dir
                )

            self.assertEqual(
                result,
                "paul/story-001-original-title",
                "must RESUME the recorded branch, not rebuild from the new slug",
            )
            self.assertEqual(_get_current_branch(td), "paul/story-001-original-title")
            branches = subprocess.run(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=td,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn(
                "paul/story-001-retitled-story",
                branches,
                "the new title slug must NOT cut a second, empty story branch",
            )


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
