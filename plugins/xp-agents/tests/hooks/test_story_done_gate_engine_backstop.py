#!/usr/bin/env python3
"""The mark-done gate, dropped BELOW the shell into the engine handlers.

Split from test_story_done_gate.py (was 539 lines) when it crossed the
500-line cap. The Bash-hook-level gate (the regex-driven `pre_tool_bash`
half of this doctrine) lives in test_story_done_gate_bash_hook.py. Shared
fixtures (`_GateCase`, `_done_cmd`, `_BASE`, `_STORY_BRANCH`) live in
_story_done_gate_helpers.py.

The proof is derived from GIT, never from a recorded token: branch ABSENCE
proves the merge, because no delete path deletes an unmerged branch --
`delete_branch` proves `is_merged_into` itself before deleting.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_store
from _story_done_gate_helpers import _BASE, _CLI, _STORY_BRANCH, _GateCase
from conftest import run_cli


class TestBackstopAtEngineAltitude(_GateCase):
    """The gate, dropped BELOW the shell into the engine handlers.

    The Bash-regex gate reads the literal command text, so an id hidden in a shell
    variable (`update-story "$SID" done`) slips past every regex — the hook never
    sees the resolved value. The engine handler does: by the time `_cmd_update_story`
    runs, the shell has expanded `$SID` to the real id. Pinning the same git-derived
    proof there closes the evasion at the altitude where every writer of `status`
    converges. Same proof, one layer down; driven end-to-end through the CLI.
    """

    def _cli(self, *args: str):
        return run_cli(_CLI, [*args, "--cwd", self.repo], self.smm_dir)

    def _status(self) -> str:
        loaded = sprint_store.load_sprint_required(self.smm_dir)
        return loaded["stories"][0]["status"]

    def test_unmerged_branch_is_refused_by_the_engine_handler(self):
        """AC: the handler refuses and the status stays unchanged — the same
        refusal the Bash hook makes, now reachable when the hook is bypassed."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli("update-story", "story-001", "done")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)
        self.assertIn(_BASE, result.stderr)
        self.assertEqual(self._status(), "closing", "status must not have moved")

    def test_shell_variable_evasion_is_closed_here(self):
        """The headline. The Bash hook cannot gate `update-story "$SID" done`: it
        sees the literal `$SID`, which is no story, so it waves the mark-done
        through. The engine handler, handed the RESOLVED id the shell produced,
        refuses. This test pairs both altitudes on one repo+sprint.
        """
        self._unmerged_story_branch()
        self._seed_sprint()

        # Shell altitude: the variable form evades the regex gate — not blocked.
        evasion = (
            'python3 /path/to/sprint_cli.py --smm-dir /tmp/smm update-story "$SID" done'
        )
        self.assertIsNone(self._run(evasion), "the shell-var form evades the hook")

        # Engine altitude: the shell resolved $SID, so the real id lands here.
        result = self._cli("update-story", "story-001", "done")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)

    def test_update_story_if_new_done_is_refused_rc2(self):
        """The compare-and-swap writer of `done`, gated too. Its block code is
        rc=2 (bad input), distinct from the rc=1 that means it lost the CAS race."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli(
            "update-story-if", "story-001", "--expected", "closing", "--new", "done"
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(_STORY_BRANCH, result.stderr)
        self.assertEqual(self._status(), "closing")

    def test_absent_branch_marks_done_through_the_engine(self):
        """AC: a merged-and-cleaned-up story (branch gone) marks done — absence is
        proof of merge, so the backstop allows it end-to-end."""
        self._seed_sprint()  # branch_name names a branch that was never created

        result = self._cli("update-story", "story-001", "done")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "done")

    def test_non_done_transition_is_not_gated(self):
        """The backstop fires ONLY on `done`. An honest `in-progress` move on a
        story whose branch is unmerged must pass — merged_block inspects current
        merge state, so gating it unconditionally would block ordinary work."""
        self._unmerged_story_branch()
        self._seed_sprint()

        result = self._cli("update-story", "story-001", "in-progress")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "in-progress")

    def test_update_story_if_to_a_non_done_status_is_not_gated(self):
        """The CAS control: `--new closing` is not `done`, so the backstop stays
        out of the way and the swap succeeds."""
        self._seed_sprint(branch=None)  # reviewing→closing, no merge to prove

        result = self._cli(
            "update-story-if",
            "story-001",
            "--expected",
            "closing",
            "--new",
            "reviewing",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._status(), "reviewing")


if __name__ == "__main__":
    unittest.main()
