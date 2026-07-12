#!/usr/bin/env python3
"""Tests for the re-slice's branch leg — create_sprint_branch resuming.

Split out of test_branching_sprint.py at the commit that crossed the 500-line
cap (story-005). The split runs along the seam of the story, not the file: this
file holds ONLY the new re-slice suites, so test_branching_sprint.py stays
byte-identical — its get_story_base_branch tests are story-008's ground, and a
move would have manufactured a merge collision for no benefit.

The re-slice has two legs and needs BOTH. sprint_cli's `create` carries the
recorded branch names forward (tests/engine/test_sprint_cli_create.py); this
file pins the second leg — create_sprint_branch resuming the branch RECORDED
for the sprint rather than rebuilding it from a goal slug that may have
changed. Without it, /xp-sprint-start's own order (create, THEN create-sprint)
would overwrite the preserve seconds after it ran.
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

_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_write_sprint_json = _bf.write_sprint_json


def _branches(td: str) -> list[str]:
    out = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=td,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(b.strip() for b in out.splitlines() if b.strip())


class TestCreateSprintBranchResumesRecordedBranch(unittest.TestCase):
    """The second leg of the re-slice preserve.

    /xp-sprint-start runs `create` and THEN `create-sprint --slug <goal-slug>`.
    create_sprint_branch used to rebuild the name from the slug it was handed
    and re-record it unconditionally — so on a re-slice with a rewritten goal it
    would overwrite the branch the CLI preserve had just carried, cut a NEW empty
    branch from the new slug, and orphan the real sprint branch. The preserve
    would have survived a raw-CLI re-slice only. Useless.

    So: resume the branch RECORDED for this sprint_id rather than recomputing it
    from a goal that may have changed. Keyed on sprint_id — the same key as the
    CLI preserve. One key, both legs.
    """

    def test_resumes_recorded_branch_when_goal_was_rewritten(self):
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-031-original-goal"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-031", "rewritten goal")
            sprint = sprint_store.load_sprint_required(smm_dir)
            sprint["branch_name"] = "paul/sprint-031-original-goal"
            sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_sprint_branch(
                    td, "sprint-031", "rewritten-goal", smm_dir
                )

            self.assertEqual(result, "paul/sprint-031-original-goal")
            self.assertEqual(_get_current_branch(td), "paul/sprint-031-original-goal")
            self.assertNotIn(
                "paul/sprint-031-rewritten-goal",
                _branches(td),
                "the new goal slug must NOT cut a second, empty sprint branch",
            )
            sprint = sprint_store.load_sprint_required(smm_dir)
            self.assertEqual(sprint["branch_name"], "paul/sprint-031-original-goal")

    def test_different_sprint_id_recomputes_from_slug(self):
        """The rollover control, and the falsifiability check on the key: a
        resume keyed on 'a branch_name is recorded' rather than on sprint_id
        would wrongly resume sprint-031's branch for sprint-032."""
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-031-old"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            # sprint.json still records the PREVIOUS sprint (the rollover
            # overwrites it in place, so create-sprint can run before it turns
            # over) — its branch must not be resumed for a different sprint_id.
            _write_sprint_json(smm_dir, "sprint-031", "old goal")
            sprint = sprint_store.load_sprint_required(smm_dir)
            sprint["branch_name"] = "paul/sprint-031-old"
            sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_sprint_branch(
                    td, "sprint-032", "fresh", smm_dir
                )

            self.assertEqual(result, "paul/sprint-032-fresh")
            self.assertEqual(_get_current_branch(td), "paul/sprint-032-fresh")


class TestResliceThroughSprintStartOrder(unittest.TestCase):
    """E2E, no mocks on the CLI legs: the near-miss, reproduced through the
    order /xp-sprint-start actually runs — `create` (SKILL.md:146) and THEN
    `create-sprint --slug <goal-slug>` (SKILL.md:201-205).

    This is the test that catches the miss. Fixing only the CLI preserve leaves
    it red: create-sprint would overwrite the carried branch seconds later.
    """

    def _sprint_cli(self, smm_dir: Path, args: list[str], stdin: str | None = None):
        cli = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"
        return subprocess.run(
            [sys.executable, str(cli), "--smm-dir", str(smm_dir), *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
        )

    def _payload(self, goal: str) -> str:
        import json

        return json.dumps(
            {
                "sprint_id": "sprint-031",
                "goal": goal,
                "started": "2026-04-22",
                "milestone": "test",
                "stories": [
                    {
                        "id": "story-001",
                        "title": "Test",
                        "status": "in-progress",
                        "dependencies": [],
                        "milestone_ref": "test",
                        "design_sources": "test",
                        "context": "test",
                        "file_domain": [],
                        "interface_contracts": [],
                        "acceptance_criteria": ["test"],
                    }
                ],
            }
        )

    def test_reslice_keeps_the_sprint_branch_and_orphans_nothing(self):
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            # Sprint-start, first run: create, then cut the sprint branch.
            self._sprint_cli(smm_dir, ["create"], self._payload("original goal"))
            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(
                    td, "sprint-031", "original-goal", smm_dir
                )
            # A teammate's story branch is recorded and live.
            sprint_store.set_story_branch(smm_dir, "story-001", "paul/story-001-test")
            original = sprint_store.load_sprint_required(smm_dir)["branch_name"]
            self.assertEqual(original, "paul/sprint-031-original-goal")

            # The re-slice: same sprint_id, rewritten goal, through the SAME
            # two-step order the skill uses.
            self._sprint_cli(smm_dir, ["create"], self._payload("rewritten goal"))
            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(
                    td, "sprint-031", "rewritten-goal", smm_dir
                )

            sprint = sprint_store.load_sprint_required(smm_dir)
            self.assertEqual(sprint["goal"], "rewritten goal", "re-slice must apply")
            self.assertEqual(
                sprint["branch_name"],
                original,
                "sprint.json must still record the ORIGINAL sprint branch",
            )
            self.assertEqual(
                sprint["stories"][0]["branch_name"],
                "paul/story-001-test",
                "the live teammate branch must survive — else it reads as an orphan",
            )
            self.assertNotIn(
                "paul/sprint-031-rewritten-goal",
                _branches(td),
                "no orphan goal-slug branch may be created",
            )

            # The whole point: the story base still resolves to the sprint
            # branch, not to the primary branch (which releases).
            with patch("branching.identity.user_namespace", return_value="paul"):
                base = branching.get_story_base_branch(smm_dir, td)
            self.assertEqual(base, original)
            self.assertNotEqual(base, "main")


_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")


class TestResliceCLIReportsResumed(unittest.TestCase):
    """The CLI must not call a RESUMED branch `created:`.

    branching_cli._cmd_create_sprint derives its resumed/created verdict from
    the SLUG-built name, on the old assumption that create_sprint_branch always
    builds the name from the slug it was handed. Now that it can return the
    RECORDED branch instead, that assumption breaks on exactly the flow this
    story creates: on a re-slice the slug-built name (`-rewritten-goal`) does
    NOT exist — that is the whole point — so `existed` is False and the CLI
    prints `created:` for a branch it resumed.

    Not cosmetic. SKILL.md Step 8 routes on this token: `resumed:` triggers the
    AskUserQuestion adopt/rename prompt, and create_sprint_branch's own
    docstring calls that prompt "the only rename path" after a goal rewrite. A
    false `created:` makes that path unreachable on every re-slice — the one
    case it was documented to serve.
    """

    def _cli(self, args: list[str], smm_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, _SCRIPT, "--smm-dir", str(smm_dir), *args],
            capture_output=True,
            text=True,
        )

    def test_reslice_prints_resumed_not_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-031", "original goal")

            first = self._cli(
                [
                    "create-sprint",
                    "--cwd",
                    td,
                    "--sprint",
                    "sprint-031",
                    "--slug",
                    "original-goal",
                ],
                smm_dir,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                first.stdout.strip(), "created: test/sprint-031-original-goal"
            )

            # The re-slice: same sprint_id, goal rewritten, so the skill hands
            # create-sprint a NEW slug. The branch is resumed, not created.
            second = self._cli(
                [
                    "create-sprint",
                    "--cwd",
                    td,
                    "--sprint",
                    "sprint-031",
                    "--slug",
                    "rewritten-goal",
                ],
                smm_dir,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                second.stdout.strip(),
                "resumed: test/sprint-031-original-goal",
                "a resumed branch must report `resumed:` — SKILL.md Step 8 routes "
                "the adopt/rename prompt on that token",
            )


if __name__ == "__main__":
    unittest.main()
