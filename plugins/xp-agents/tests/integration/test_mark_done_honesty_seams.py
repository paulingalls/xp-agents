#!/usr/bin/env python3
"""Capstone: no route to `done` on unmerged work but an accountable bypass.

Milestone 2 closed three interacting honesty holes, each defending the same
invariant from a different altitude:

- story-001: the merge backstop below the shell, in the engine handlers, where
  every writer of `status` converges. Closes the `update-story "$SID" done`
  evasion the Bash regex gate structurally cannot see.
- story-002: `--force-unmerged` on update-story-if — the ONLY way through, and
  it costs a recorded debt event.
- story-003: a PreToolUse:Bash refusal of raw `git branch -d/-D` of an unmerged
  story branch, protecting the keystone story_done_gate rests on: branch
  ABSENCE is proof of merge.

Each story has unit tests. This file proves they COMPOSE, through real
subprocesses on one shared SMM — the seam no per-story review reaches. Two
things here are genuinely new rather than a re-test of any unit: seam 3 gets
its first subprocess-level coverage (every existing test calls
pre_tool_bash.run() in-process), and nothing else drives seam 3 together with
seams 1 and 2.

Assertions pin the SPECIFIC refusal text, never a bare exit code.
`_unmerged_story_branch_delete_block` has TWO exit-2 arms and both name the
branch — the real non-ancestor refusal, and a fail-closed "base cannot be
honestly resolved" arm. A fixture with a wrong base would satisfy the loose
assertion while proving nothing, which is exactly the reachability-vs-reality
failure this milestone exists to close.

Test-only: a broken seam here means STOP and surface it, not a production patch.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_store
from _branching_fixtures import (
    append_commit,
    branch_exists,
    seed_sprint_with_stories,
    write_system_context,
)
from _cli_helpers import run_cli
from _hook_inputs import _make_bash_input
from conftest import _IntegrationTestCase

_BASE = "main"
_STORY_ID = "story-001"
_STORY_BRANCH = "paulingalls/story-001-capstone-seam"
_SPRINT_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"

# The real non-ancestor refusals. The two seams word it differently, and the
# difference is load-bearing — matching the wrong one silently matches nothing.
_DELETE_REFUSAL = f"it is not merged into {_BASE}"  # pre_tool_bash
_GATE_REFUSAL = f"is NOT merged into {_BASE}"  # story_done_gate


class TestMarkDoneHonestySeamsCompose(_IntegrationTestCase):
    """The SEAMS between story-001/002/003 — not a re-test of any one unit."""

    def setUp(self):
        super().setUp()
        self._reset_repo_to_main()
        self._make_unmerged_story_branch()
        seed_sprint_with_stories(
            self.smm_dir,
            [(_STORY_ID, "closing")],
            base_branch=_BASE,
            story_branches={_STORY_ID: _STORY_BRANCH},
        )
        write_system_context(self.smm_dir, 2)

    def tearDown(self):
        subprocess.run(
            ["git", "checkout", "-f", _BASE], cwd=self.tmpdir, capture_output=True
        )
        subprocess.run(
            ["git", "branch", "-D", _STORY_BRANCH],
            cwd=self.tmpdir,
            capture_output=True,
        )
        super().tearDown()

    def _make_unmerged_story_branch(self) -> None:
        """A story branch carrying one commit that `main` does not have."""
        subprocess.run(
            ["git", "checkout", "-b", _STORY_BRANCH],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        append_commit(str(self.tmpdir), "story-work.txt")
        subprocess.run(
            ["git", "checkout", _BASE], cwd=self.tmpdir, capture_output=True, check=True
        )

    def _hook(self, command: str) -> subprocess.CompletedProcess:
        """Drive the REAL pre_tool_bash.py as a subprocess, as the harness does."""
        return self._run_script(
            "pre_tool_bash.py",
            _make_bash_input(command=command, cwd=str(self.tmpdir)),
        )

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(_SPRINT_CLI, [*args, "--cwd", str(self.tmpdir)], self.smm_dir)

    def _mark_done_cmd(self, story_ref: str) -> str:
        return (
            f"python3 {_SPRINT_CLI} --smm-dir {self.smm_dir} "
            f"update-story {story_ref} done"
        )

    def _status(self) -> str:
        return sprint_store.load_sprint_required(self.smm_dir)["stories"][0]["status"]

    def _bypass_debts(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("type") == "debt" and "MERGE GATE BYPASSED" in e.get("content", "")
        ]

    def test_no_route_to_done_on_unmerged_work_without_a_recorded_bypass(self):
        """Every route to a dishonest `done` is closed, and they agree.

        Drives all three seams in sequence on one repo + one SMM.
        """
        # Route 1 (seam 3): fake the merge by deleting the branch. Absence is
        # what the gate reads as proof, so the delete must be refused.
        delete = self._hook(f"git branch -D {_STORY_BRANCH}")
        self.assertEqual(delete.returncode, 2, delete.stderr)
        self.assertIn(_DELETE_REFUSAL, delete.stderr)
        self.assertTrue(
            branch_exists(str(self.tmpdir), _STORY_BRANCH),
            "the refused branch must survive — a deleted one reads as merged",
        )

        # Route 2 (seam 1, shell altitude): mark done with a literal id.
        literal = self._hook(self._mark_done_cmd(_STORY_ID))
        self.assertEqual(literal.returncode, 2, literal.stdout)

        # Route 3 (seam 1, the evasion): hide the id behind a shell variable.
        # The hook reads literal command text, so it CANNOT resolve $SID and
        # waves it through. Asserting the wave-through is the point: if this
        # ever blocks, the engine backstop below is unreachable — inert code
        # that four reviews would call correct.
        evasion = self._hook(self._mark_done_cmd('"$SID"'))
        self.assertEqual(
            evasion.returncode,
            0,
            "the shell-var form must evade the hook; if it stops evading, the "
            "engine backstop is no longer load-bearing and this capstone is "
            "proving nothing",
        )

        # Route 3 continued (seam 1, engine altitude): the shell expanded $SID,
        # so the resolved id reaches the handler. THIS is what closes the hole.
        engine = self._cli("update-story", _STORY_ID, "done")
        self.assertEqual(engine.returncode, 1, engine.stderr)
        self.assertIn(_GATE_REFUSAL, engine.stderr)

        # The three agree: nothing moved, and nothing was laundered as a bypass.
        self.assertEqual(self._status(), "closing", "status must not have moved")
        self.assertEqual(self._bypass_debts(), [], "no bypass was recorded")

    def test_the_only_route_through_is_an_accountable_bypass(self):
        """--force-unmerged marks done, at the price of a recorded debt.

        And the keystone does NOT weaken afterwards: seam 3 keys on git
        ancestry, never on story status, so a force-marked story's branch is
        still protected. That is the seam question no unit test asks.
        """
        forced = self._cli(
            "update-story-if",
            _STORY_ID,
            "--expected",
            "closing",
            "--new",
            "done",
            "--force-unmerged",
            "merge landed as part of a sibling story; branch is redundant",
        )

        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(self._status(), "done")

        debts = self._bypass_debts()
        self.assertEqual(
            len(debts), 1, "the bypass must be on the record, exactly once"
        )
        self.assertIn(_STORY_ID, debts[0]["content"])

        # The branch is still unmerged, so it is still protected. A recorded
        # bypass buys a `done`, not permission to erase the evidence.
        delete = self._hook(f"git branch -D {_STORY_BRANCH}")
        self.assertEqual(delete.returncode, 2, delete.stderr)
        self.assertIn(_DELETE_REFUSAL, delete.stderr)


if __name__ == "__main__":
    unittest.main()
