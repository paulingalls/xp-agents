#!/usr/bin/env python3
"""Which checkout owns each field of the review-cycle record.

The record carried two fields whose owners are not the same checkout:

  - `last_review_commit` is a sha, and its only consumer resolves it inside
    the history of the repo the commit lands in;
  - the two review flags belong to the session that ran the review, which is
    where every hook that sets them is running.

Holding both in ONE agent-keyed file forced each site to pick one owner for
both. The commit sites picked the target repo, the seven flag sites picked the
session, and they agree only while the two are the same directory. `git -C
<other-repo> commit` — the form this project's close skills tell an agent to
prefer — is exactly when they are not: the gate reads a record
/xp-quality-review never writes, and no rerun can clear it, because every
writer writes the other file.

The split is what makes the collision impossible. These pins are what keep the
two fields' cwds from drifting back together.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import review_records

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import pre_tool_bash_commit_gates
import review_cycle_done
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input

_LEAD_CWD = "/tmp"
_LEAD_KEY = "main"
_TEAMMATE_KEY = "worktree-story-999"
_OVER_THRESHOLD = ["a.py", "b.py", "c.py"]


class _TwoCheckoutCase(_HookTestCase):
    """A lead session whose commit lands in a different checkout.

    The teammate directory must really exist: `parse_effective_cwd` resolves a
    `-C` target by `is_dir()`, and an unresolvable one falls back to the
    caller's cwd — which would make the two keys agree again and hide the very
    divergence under test.
    """

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.teammate_cwd = Path(self._tmp.name) / _TEAMMATE_KEY
        self.teammate_cwd.mkdir()
        self.commit_cmd = f"git -C {self.teammate_cwd} commit -m 'fix'"

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def lead_runs_quality_review(self) -> None:
        """The real PostToolUse leg: its payload cwd is the LEAD's, because
        that is the process the hook fires in — whatever repo the review was
        about."""
        review_cycle_done.run(
            {
                "agent_id": "main",
                "cwd": _LEAD_CWD,
                "tool_name": "Skill",
                "tool_input": {"skill": "xp-quality-review"},
            },
            smm_dir=self.smm_dir,
        )


class TestTheFlagsFollowTheSession(_TwoCheckoutCase):
    def _gate(self) -> list[str]:
        with (
            patch("commits.get_staged_files", return_value=[]),
            patch(
                "commits.get_code_files_for_review", return_value=list(_OVER_THRESHOLD)
            ),
        ):
            return pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, self.commit_cmd, _LEAD_CWD
            )

    def test_the_gate_accepts_the_review_the_lead_session_ran(self):
        """The block: unclearable, because re-running the review writes the
        lead's record every time and the gate reads the target repo's."""
        self.lead_runs_quality_review()

        self._gate()

    def test_a_commit_with_no_review_anywhere_still_blocks(self):
        """Non-vacuity: the leg above must not pass by never blocking."""
        with self.assertRaises(_common.BlockedError) as ctx:
            self._gate()
        self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_a_review_run_in_the_target_checkout_does_not_satisfy_the_lead(self):
        """The flags are the session's, so a teammate's own review is not the
        lead's. Fails toward one extra review, never toward an unreviewed
        commit."""
        review_records.set_review_flag(
            self.smm_dir, _TEAMMATE_KEY, "quality_review_done"
        )

        with self.assertRaises(_common.BlockedError):
            self._gate()


class TestTheWatermarkFollowsTheRepo(_TwoCheckoutCase):
    def test_the_gate_measures_from_the_target_repos_watermark(self):
        """The sha is only resolvable in the repo whose history holds it —
        `_run_git` fails on a foreign one and the count silently drops to
        zero, disabling the gate."""
        review_records.write_review_watermark(
            self.smm_dir, _TEAMMATE_KEY, "teammate-sha"
        )
        review_records.write_review_watermark(self.smm_dir, _LEAD_KEY, "lead-sha")
        self.lead_runs_quality_review()

        with (
            patch("commits.get_staged_files", return_value=[]),
            patch("commits.get_code_files_for_review", return_value=[]) as spy,
        ):
            pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, self.commit_cmd, _LEAD_CWD
            )

        self.assertEqual(spy.call_args.args[1], "teammate-sha")

    def test_a_commit_stamps_the_repo_it_landed_in_and_clears_the_session(self):
        """One commit, two records: the watermark advances in the target repo,
        the flags clear for the session that ran the review."""
        self.lead_runs_quality_review()

        with patch_commits(files=["a.py"], body="fix", head_sha="landed-sha"):
            bash_post_tool.run(
                _make_bash_input(
                    command=self.commit_cmd,
                    stdout="[main landed] fix\n 1 file changed",
                    cwd=_LEAD_CWD,
                ),
                smm_dir=self.smm_dir,
            )

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _TEAMMATE_KEY),
            "landed-sha",
        )
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _LEAD_KEY), ""
        )
        self.assertFalse(
            review_records.read_review_flags(self.smm_dir, _LEAD_KEY)[
                "quality_review_done"
            ],
            "the commit ends the review cycle of the session that ran it",
        )


if __name__ == "__main__":
    unittest.main()
