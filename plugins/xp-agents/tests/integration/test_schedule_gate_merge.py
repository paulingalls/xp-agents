#!/usr/bin/env python3
"""End-to-end: a real conflicted merge opens the schedule gate, and committing
the merge closes it again (story-016 AC-6).

The unit suite stubs `identity.merge_in_progress` at its seam, which proves the
gate CONSULTS the probe but not that the probe reads what git actually writes.
This drives the real `pre_tool_write.py` as a subprocess against a real repo in a
real conflicted-merge state — no mocks, no monkeypatching anywhere in this file.

The incident it reproduces: a v5.5.1 back-merge onto a sprint branch with stories
scheduled and none in motion. Resolving the conflicts meant EDITING the conflicted
files, every such Edit was refused, and the session needed a procedural
workaround. The commit gate already had an escape for this exact case.

Both directions run against ONE repo and ONE conflicted file, differing only in
whether the merge is still in progress. Two false-greens are designed against:

  1. An ALLOW that rides a sibling exemption rather than the merge. The branch
     here is a SPRINT branch (not free-shaped, so the free leg cannot carry it)
     and the target is the conflicted file INSIDE the tree (so the out-of-tree
     leg cannot), and both are asserted rather than assumed.
  2. A BLOCK that is really some other gate. `pre_tool_write` raises from five
     places; the refusal assertion names the schedule gate's own message and
     excludes the corrupt-sprint one.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branch_names
import identity
from _branching_fixtures import get_current_branch_at
from conftest import SPRINT_SCHEDULED_ONLY, _IntegrationTestCase, _make_write_input

# The branch the recorded misfire happened on: a sprint reconciliation branch.
# Deliberately neither free-shaped nor a story branch, so no other exemption leg
# can explain an allow here.
_SPRINT_BRANCH = "paulingalls/sprint-004-back-merge"
_SIDE_BRANCH = "paulingalls/sprint-004-incoming"
_CONFLICTED = "conflicted.txt"


class TestMergeInProgressOpensTheScheduleGate(_IntegrationTestCase):
    """Branch-mutating, so its own TestCase: a leaked branch or a leaked
    MERGE_HEAD would hand a sibling suite a repo whose gate is already exempt."""

    def setUp(self):
        super().setUp()
        self._reset_repo_to_main()
        self.addCleanup(self._cleanup_repo)
        # The gate window: stories scheduled, nothing in motion.
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

    # -- fixture -----------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=check,
        )

    def _cleanup_repo(self) -> None:
        """Abort any surviving merge, then drop both branches.

        Registered BEFORE the repo is mutated so a failure partway still tears
        down. Quiet (`check=False`): the point is to leave the shared repo usable,
        and one leg or the other is a no-op depending on how far the test got.
        """
        self._git("merge", "--abort", check=False)
        self._reset_repo_to_main()
        for branch in (_SPRINT_BRANCH, _SIDE_BRANCH):
            self._git("branch", "-D", branch, check=False)

    def _target(self) -> str:
        return str(self.tmpdir / _CONFLICTED)

    def _start_conflicting_merge(self) -> None:
        """Leave the repo mid-merge on `_SPRINT_BRANCH`, `_CONFLICTED` conflicted.

        Guards that the merge really did conflict, so a future non-conflicting
        fixture edit cannot make every assertion below vacuous.
        """
        target = self.tmpdir / _CONFLICTED
        self._git("checkout", "-b", _SPRINT_BRANCH)
        target.write_text("shared base\n")
        self._git("add", _CONFLICTED)
        self._git("commit", "-m", "seed the file both sides will edit")

        self._git("checkout", "-b", _SIDE_BRANCH)
        target.write_text("incoming change\n")
        self._git("commit", "-am", "incoming edit")

        self._git("checkout", _SPRINT_BRANCH)
        target.write_text("local change\n")
        self._git("commit", "-am", "local edit")

        merge = self._git("merge", _SIDE_BRANCH, check=False)
        self.assertNotEqual(merge.returncode, 0, "the merge was expected to conflict")
        self.assertTrue(identity.merge_in_progress(str(self.tmpdir)))

    def _resolve_and_commit_the_merge(self) -> None:
        (self.tmpdir / _CONFLICTED).write_text("resolved\n")
        self._git("add", _CONFLICTED)
        self._git("commit", "--no-edit")
        self.assertFalse(identity.merge_in_progress(str(self.tmpdir)))

    def _edit(self, target: str) -> subprocess.CompletedProcess:
        """Drive the real hook for an Edit of `target` — the tool the operator
        reaches for to resolve a conflict."""
        return self._run_script(
            "pre_tool_write.py",
            _make_write_input(
                tool_name="Edit",
                tool_input={"file_path": target, "content": "resolved\n"},
                cwd=str(self.tmpdir),
            ),
        )

    # -- preconditions -----------------------------------------------------

    def _assert_no_sibling_exemption_can_explain_an_allow(self) -> None:
        branch = get_current_branch_at(self.tmpdir)
        self.assertEqual(branch, _SPRINT_BRANCH)
        self.assertFalse(
            branch_names.is_free_branch(branch),
            "a free-shaped branch would exempt the write on its own",
        )
        target = Path(self._target())
        self.assertIn(self.tmpdir.resolve(), target.resolve().parents)
        self.assertNotIn(self.smm_dir.resolve(), target.resolve().parents)

    def _assert_gate_window_is_real(self) -> None:
        stories = json.loads((self.smm_dir / "sprint.json").read_text())["stories"]
        self.assertTrue(any(s["status"] == "scheduled" for s in stories))
        self.assertFalse(
            any(s["status"] in ("in-progress", "reviewing", "closing") for s in stories)
        )

    # -- assertions --------------------------------------------------------

    def _assert_allowed(self, result: subprocess.CompletedProcess) -> None:
        """Exit 0 EXACTLY, and no block on stdout either.

        `!= 2` would call a traceback (exit 1) a pass — production allows such a
        write, for a catastrophic reason. And PreToolUse has a SECOND block
        channel: exit 0 carrying `decision: block` / `permissionDecision: deny`
        on stdout. Reading only the exit code would score that as an allow.
        """
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        if result.stdout.strip():
            payload = json.loads(result.stdout)
            self.assertNotEqual(payload.get("decision"), "block", result.stdout)
            self.assertNotEqual(
                payload.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
                result.stdout,
            )

    def _assert_blocked_by_the_schedule_gate(
        self, result: subprocess.CompletedProcess
    ) -> None:
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("xp-schedule", result.stderr)
        self.assertNotIn("cannot be read", result.stderr)

    # -- the two directions ------------------------------------------------

    def test_an_edit_to_the_conflicted_file_is_allowed_mid_merge(self):
        """The exemption, at real git fidelity. MERGE_HEAD is set, so resolving
        the conflict is not "story code written before promotion"."""
        self._assert_gate_window_is_real()
        self._start_conflicting_merge()
        self._assert_no_sibling_exemption_can_explain_an_allow()

        self._assert_allowed(self._edit(self._target()))

    def test_the_same_edit_is_refused_once_the_merge_is_committed(self):
        """The sole-variable control, and the reason the exemption is safe. Same
        repo, same branch, same file, same sprint — only MERGE_HEAD is gone.

        Without this, the allow above passes just as well with the schedule gate
        deleted outright, and the exemption would silently be permanent.
        """
        self._assert_gate_window_is_real()
        self._start_conflicting_merge()
        self._resolve_and_commit_the_merge()
        self._assert_no_sibling_exemption_can_explain_an_allow()

        self._assert_blocked_by_the_schedule_gate(self._edit(self._target()))

    def test_the_gate_blocks_before_the_merge_starts(self):
        """The third point on the same line: on this branch, in this window, with
        no merge ever begun, the gate blocks. Pins that the fixture's own
        `checkout -b` is not what opens the door."""
        self._assert_gate_window_is_real()
        self._git("checkout", "-b", _SPRINT_BRANCH)
        (self.tmpdir / _CONFLICTED).write_text("untracked\n")

        self._assert_blocked_by_the_schedule_gate(self._edit(self._target()))


if __name__ == "__main__":
    unittest.main()
