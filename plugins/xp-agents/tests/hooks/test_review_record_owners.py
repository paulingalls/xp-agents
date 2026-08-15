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
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import append_validation
import bash_post_tool
import commits
import identity
import markers
import pre_tool_bash_commit_gates
import review_cycle_done
import review_records
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
        about.

        The leg is the REVIEWER AGENT returning, not the skill launching: the
        Skill payload fires before the review has run and no longer sets the
        flag.
        """
        review_cycle_done.run(
            {
                "agent_id": "main",
                "cwd": _LEAD_CWD,
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "xp-agents:xp-code-reviewer"},
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
        """The sha is only resolvable in the repo whose history holds it: a
        foreign one fails `_run_git` and drops its whole leg from the count,
        so the gate measures from the staged set alone."""
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

    @patch("commits.subprocess.run")
    def test_a_watermark_that_does_not_resolve_still_counts_the_staged_set(
        self, mock_run
    ):
        """The other half of the same trip: once a foreign sha IS in a
        checkout's record, `{sha}..HEAD` is `fatal: bad object` on every commit
        there afterward. Discarding the staged names already collected would
        count changed code files as 0 and disarm the gate for good — the one
        direction it must never fail in."""

        def side_effect(cmd, **_kwargs):
            if "--cached" in cmd:
                return SimpleNamespace(returncode=0, stdout="src/a.py\0src/b.py\0")
            return SimpleNamespace(returncode=128, stdout="")

        mock_run.side_effect = side_effect

        self.assertEqual(
            commits.get_code_files_for_review(_LEAD_CWD, "foreign-sha"),
            ["src/a.py", "src/b.py"],
        )

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


class TestTheWatermarkSurvivesTheSplit(_HookTestCase):
    """An install upgrading across the split holds its sha in the OLD record.

    The FLAGS kept their file, so they migrated for free; the watermark got a
    new one, and every checkout that reviewed before the upgrade has nothing in
    it. Reading only the new record answers "" there, which drops the
    `{sha}..HEAD` leg entirely — the gate measures from the staged set alone
    and lets through exactly the commit the old record would have blocked. Once
    per checkout, in the fail-open direction, which is why the read migrates.
    """

    def test_a_pre_split_record_still_answers_the_watermark(self):
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_CYCLE,
            {"last_review_commit": "old-sha", "quality_review_done": True},
            _LEAD_KEY,
        )

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _LEAD_KEY), "old-sha"
        )

    def test_the_new_record_wins_wherever_it_exists(self):
        """The migration is a fallback, not a merge: the first commit after the
        upgrade writes the new record, and the stale field beside the flags
        must not resurrect the sha it replaced."""
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_CYCLE,
            {"last_review_commit": "old-sha"},
            _LEAD_KEY,
        )
        review_records.write_review_watermark(self.smm_dir, _LEAD_KEY, "new-sha")

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _LEAD_KEY), "new-sha"
        )

    def test_ending_a_cycle_elsewhere_does_not_erase_the_only_watermark(self):
        """The migration's own window is where it can be lost.

        `end_review_cycle` clears the flags before writing the watermark, and
        under `git -C <other>` those are DIFFERENT keys — so the first
        post-upgrade commit clears this checkout's flags while stamping
        another's watermark. A clear that wrote only the defaults dropped the
        pre-split sha with them, permanently, and the fallback then had nothing
        to fall back to: the `{sha}..HEAD` leg goes away for good and the gate
        measures from the staged set alone. Fail-open, once, silently.
        """
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_CYCLE,
            {"last_review_commit": "old-sha", "quality_review_done": True},
            _LEAD_KEY,
        )

        review_records.end_review_cycle(
            self.smm_dir, _TEAMMATE_KEY, _LEAD_KEY, "landed-elsewhere"
        )

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _LEAD_KEY), "old-sha"
        )
        self.assertFalse(
            review_records.read_review_flags(self.smm_dir, _LEAD_KEY)[
                "quality_review_done"
            ],
            "the cycle still has to END — preserving the sha must not keep the "
            "review flags alive",
        )

    def test_neither_record_is_still_no_watermark(self):
        """Non-vacuity: a fresh checkout must not read a sha out of nowhere."""
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, _LEAD_KEY), ""
        )


class TestAKeyDerivedFromAPathIsAlwaysUsable(_TwoCheckoutCase):
    """A path the commit COMMAND names now decides a marker filename, and a
    path is a much wider input than the hook payload it replaced there.

    `extract_worktree_name` returns whatever segment starts with the teammate
    prefix, and the marker layer validates that against an allowlist and raises
    on a miss. The gate does not catch ValueError — `pre_tool_bash` catches only
    BlockedError — so an unrepresentable segment took the PreToolUse hook down
    with a traceback and skipped every advisory below it. Falling back to the
    default key is the same answer this resolver already gives any path that is
    not one of ours, and no checkout this project creates can reach it: worktree
    names are built from story ids.
    """

    def _key_for(self, segment: str) -> str:
        path = Path(self._tmp.name) / segment
        path.mkdir(exist_ok=True)
        return identity.review_watermark_key(str(path))

    def test_a_worktree_segment_the_marker_layer_rejects_falls_back(self):
        key = self._key_for("worktree-story-a.b")

        append_validation.validate_agent_id(key)
        self.assertEqual(key, _LEAD_KEY)

    def test_a_representable_worktree_segment_is_still_its_own_key(self):
        """Non-vacuity: the fallback must not swallow every worktree, which
        would merge two checkouts' records — the collision this split removed."""
        self.assertEqual(self._key_for("worktree-story-042"), "worktree-story-042")

    def test_the_gate_survives_a_commit_into_such_a_path(self):
        """End to end: the hook must degrade, not raise."""
        self.commit_cmd = (
            f"git -C {Path(self._tmp.name) / 'worktree-story-a.b'} commit -m 'fix'"
        )
        Path(self._tmp.name, "worktree-story-a.b").mkdir(exist_ok=True)
        self.lead_runs_quality_review()

        with (
            patch("commits.get_staged_files", return_value=[]),
            patch("commits.get_code_files_for_review", return_value=[]),
        ):
            pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, self.commit_cmd, _LEAD_CWD
            )


if __name__ == "__main__":
    unittest.main()
