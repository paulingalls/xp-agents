#!/usr/bin/env python3
"""Tests for branching.create_story_branch — story-branch creation/resume."""

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
_make_feature_commit = _bf.append_commit


def _make_sprint_branch(td: str, name: str) -> None:
    """Cut the sprint branch the story base will resolve to.

    Without it, a seeded sprint at stage 2+ whose branch does not exist is the
    unresolvable state create_story_branch now refuses.
    """
    _bf.make_branch(td, name)


class TestCreateStoryBranch(unittest.TestCase):
    def test_creates_and_checks_out_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "branch-lifecycle", smm_dir
                )

            self.assertEqual(result, "paul/story-001-branch-lifecycle")
            self.assertEqual(_get_current_branch(td), "paul/story-001-branch-lifecycle")

    def test_skips_at_stage_zero(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_skips_when_no_system_context(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_resume_existing_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/story-001-resume"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "resume", smm_dir
                )

            self.assertEqual(result, "paul/story-001-resume")
            self.assertEqual(_get_current_branch(td), "paul/story-001-resume")

    def test_resume_fast_forwards_when_behind_base(self):
        """Story branch resumed mid-sprint must fast-forward to the
        current sprint base, not snap to the stale scaffold-time HEAD.

        Reproduces concern dc0340ac5582: sprint-start scaffolds story
        branches off pre-iter HEAD; later, the sprint base advances
        (e.g., a prior story was merged in); resuming the story branch
        without fast-forward leaves it on the stale base — exactly what
        happened in this session when story-002 had to manually rebase
        onto story-001's commits.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            # Scaffold-time: create the story branch off the original main tip.
            subprocess.run(
                ["git", "branch", "paul/story-001-ff"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            # Base advances after scaffold.
            _make_feature_commit(td, "base-advance.txt")
            advanced_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            # Resume the scaffolded branch with the advanced base.
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(td, "story-001", "ff", smm_dir)

            self.assertEqual(result, "paul/story-001-ff")
            self.assertEqual(_get_current_branch(td), "paul/story-001-ff")
            resumed_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                resumed_sha,
                advanced_sha,
                "Resumed story branch must fast-forward to current base; "
                f"expected {advanced_sha}, got {resumed_sha} (stale)",
            )

    def test_resume_preserves_unique_commits_no_rebase(self):
        """Story branch with its own commits ahead of base must NOT be
        silently rebased — that could lose work or surface conflicts the
        agent didn't ask to resolve. Auto-fast-forward only when safe.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            # Create + check out the story branch, make a unique commit on it.
            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-ahead"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "story-only.txt")
            story_tip = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # Switch back so we can resume.
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=td,
                capture_output=True,
                check=True,
            )

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "ahead", smm_dir
                )

            self.assertEqual(result, "paul/story-001-ahead")
            resumed_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                resumed_sha,
                story_tip,
                "Resumed story branch with unique commits must not be "
                "rewound or rebased — story tip must be preserved.",
            )

    def test_raises_when_dirty(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "dirty", smm_dir)

    def test_exits_when_existing_checkout_fails(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            fail_result = subprocess.CompletedProcess(
                ["git", "checkout"], 1, "", "error: conflict"
            )

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                # _create_or_resume_branch moved to branching_core.py — patch there.
                patch("branching_core.branch_exists", return_value=True),
                patch("branching_core._git", return_value=fail_result),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "conflict", smm_dir)


class TestCreateStoryBranchWithBase(unittest.TestCase):
    def test_forks_from_explicit_base(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_feature_commit(td, "first.txt")
            base_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            _make_feature_commit(td, "second.txt")

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-002", "chained", smm_dir, base=base_sha
                )

            self.assertEqual(result, "paul/story-002-chained")
            parent_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(parent_sha, base_sha)

    def test_default_base_uses_story_base_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "default", smm_dir
                )

            self.assertEqual(result, "paul/story-001-default")
            self.assertEqual(_get_current_branch(td), "paul/story-001-default")

    def test_cli_base_flag_passthrough(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_feature_commit(td, "first.txt")
            base_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            _make_feature_commit(td, "second.txt")

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            cli = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
            # No USER override: identity.user_namespace reads GIT CONFIG, never
            # $USER, so the subprocess namespace is the fixture repo's ("test").
            # The branch name is read back from stdout below rather than guessed.
            env = _bf.GIT_ENV
            result = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "--smm-dir",
                    str(smm_dir),
                    "create",
                    "--cwd",
                    td,
                    "--story",
                    "story-002",
                    "--slug",
                    "cli-base",
                    "--base",
                    base_sha,
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("story-002-cli-base", result.stdout)
            branch = result.stdout.strip().split(": ", 1)[1]
            head_sha = subprocess.run(
                ["git", "rev-parse", branch],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(head_sha, base_sha)


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
