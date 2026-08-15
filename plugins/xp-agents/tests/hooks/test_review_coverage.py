#!/usr/bin/env python3
"""A review covers the fixes it produces, for exactly one commit.

The gate blocks at REVIEW_CYCLE_THRESHOLD changed code files unless a review
ran, and a landed commit clears the flag. So a review's OWN fixes — the
reviewer's edits, and the act-on-findings edits the calling skill makes after
it returns — arrive at the next commit as unreviewed changes and demand a
second review, whose fixes demand a third. It terminates only when a review
comes back clean or touches fewer than the threshold. Reproduced live
(concern 0c018a40d9b9) when a close's Step 5c fixes were blocked.

The fix records what the review LOOKED AT, and lets the next commit spend that
coverage once. Two properties have to hold together and are pinned here:

  - the follow-up commit confined to reviewed files passes, and
  - the one after it does not, nor does any commit reaching outside the set.

Coverage that never expired would let a file be edited freely forever once a
review had glanced at it.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash_commit_gates
import review_cycle_done
import review_records
import subagent_stop
from conftest import _HookTestCase

_KEY = "main"
_CWD = "/tmp"


class TestCoverageIsRecordedAndAges(_HookTestCase):
    """The record itself: written, read back, and spent on a schedule."""

    def test_absent_coverage_reads_as_empty(self):
        """No review has run, so nothing is forgiven — the gate's default."""
        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_written_coverage_reads_back(self):
        review_records.write_review_coverage(self.smm_dir, _KEY, ["b.py", "a.py"])
        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"a.py", "b.py"}
        )

    def test_coverage_survives_the_commit_that_ends_its_own_review(self):
        """The reviewed work lands first. Spending coverage there would leave
        nothing for the fixes, which is the whole case this exists for."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py"])

        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"a.py"}
        )

    def test_coverage_is_spent_by_the_follow_up_commit(self):
        """Second commit consumes it. Without this the set never expires and a
        reviewed file stays permanently exempt."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py"])

        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-2")

        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_a_new_review_replaces_a_partly_aged_set(self):
        """Coverage is the LAST review's scope, not a union of every review's.
        A stale path list would forgive files the current review never saw."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["old.py"])
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")

        review_records.write_review_coverage(self.smm_dir, _KEY, ["new.py"])

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"new.py"}
        )
        # ...and its age restarts, so it still survives its own commit.
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-2")
        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"new.py"}
        )


class TestTheGateSubtractsCoverage(_HookTestCase):
    """The gate's arithmetic. Threshold applies to the UNCOVERED count."""

    def _uncovered(self, changed: list[str], covered: list[str]) -> int:
        review_records.write_review_coverage(self.smm_dir, _KEY, covered)
        return review_records.uncovered_count(
            changed, review_records.read_review_coverage(self.smm_dir, _KEY)
        )

    def test_fixes_confined_to_reviewed_files_count_zero(self):
        self.assertEqual(self._uncovered(["a.py", "b.py"], ["a.py", "b.py", "t.py"]), 0)

    def test_a_file_the_review_never_saw_still_counts(self):
        """Non-vacuity: coverage must not swallow genuinely new work."""
        self.assertEqual(self._uncovered(["a.py", "new.py"], ["a.py"]), 1)

    def test_uncovered_files_reach_the_threshold_on_their_own(self):
        self.assertEqual(self._uncovered(["x.py", "y.py"], ["a.py"]), 2)

    def test_no_coverage_counts_everything(self):
        self.assertEqual(review_records.uncovered_count(["a.py", "b.py"], set()), 2)

    def test_non_code_paths_are_the_callers_problem(self):
        """uncovered_count does no classification — it is set arithmetic on the
        list the caller already filtered. Pinned so a future caller does not
        assume it filters, and ship an ungated .md through the gate."""
        self.assertEqual(review_records.uncovered_count(["README.md"], set()), 1)


class TestOnlyAGenuineCompletionCounts(_HookTestCase):
    """WHICH event means "the review finished".

    Measured 2026-08-15, and it is not what v5.16.0 assumed: this harness
    backgrounds Agent-tool subagents, so `PostToolUse:Agent` fires when the
    TOOL CALL returns — at launch. The reviewer's own start event was stamped
    70ms AFTER the qr_complete the hook emitted for it. Keying the flag on the
    Agent tool moved the defect from skill-launch to agent-launch; it did not
    remove it.

    SubagentStop is the signal that fires at completion. Live evidence rather
    than assumption: xp-close-reviewer's SubagentStop handler recorded a
    completion for an Agent-tool xp-* subagent in this same harness, carrying
    `agent_type='xp-agents:xp-close-reviewer'`.
    """

    def _reviewer_stops(self, in_scope: list[str]) -> None:
        with patch("commits.get_code_files_for_review", return_value=in_scope):
            subagent_stop.run(
                {
                    "session_id": "t",
                    "agent_id": "rev-1",
                    "agent_type": "xp-agents:xp-code-reviewer",
                    "cwd": _CWD,
                    "last_assistant_message": "Done",
                },
                smm_dir=self.smm_dir,
            )

    def test_reviewer_completion_sets_the_flag(self):
        self._reviewer_stops(["a.py"])

        flags = review_records.read_review_flags(self.smm_dir, _KEY)
        self.assertTrue(flags["quality_review_done"])

    def test_reviewer_completion_records_its_scope(self):
        self._reviewer_stops(["a.py", "b.py"])

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"a.py", "b.py"}
        )

    def test_the_agent_tool_returning_does_neither(self):
        """The load-bearing non-vacuity pin. This payload is what the harness
        delivers at LAUNCH, so it must leave the gate armed and record nothing
        — otherwise v5.16.0's defect is still here under a new name."""
        with patch("commits.get_code_files_for_review", return_value=["a.py", "b.py"]):
            review_cycle_done.run(
                {
                    "agent_id": "main",
                    "cwd": _CWD,
                    "tool_name": "Agent",
                    "tool_input": {"subagent_type": "xp-agents:xp-code-reviewer"},
                },
                smm_dir=self.smm_dir,
            )

        flags = review_records.read_review_flags(self.smm_dir, _KEY)
        self.assertFalse(flags["quality_review_done"])
        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_the_skill_launch_does_neither(self):
        review_cycle_done.run(
            {
                "agent_id": "main",
                "cwd": _CWD,
                "tool_name": "Skill",
                "tool_input": {"skill": "xp-quality-review"},
            },
            smm_dir=self.smm_dir,
        )

        flags = review_records.read_review_flags(self.smm_dir, _KEY)
        self.assertFalse(flags["quality_review_done"])
        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_a_git_failure_records_no_coverage(self):
        """Fails toward one extra review. An empty scope forgives nothing,
        which is the safe direction when git could not be read."""
        self._reviewer_stops([])

        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_an_unrelated_subagent_does_neither(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "general-purpose",
                "cwd": _CWD,
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )

        flags = review_records.read_review_flags(self.smm_dir, _KEY)
        self.assertFalse(flags["quality_review_done"])
        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())


class TestTheGateHonoursCoverage(_HookTestCase):
    """End to end through the real gate: a review's own fixes get through."""

    def _gate(self, changed: list[str]) -> list[str]:
        with (
            patch("commits.get_staged_files", return_value=[]),
            patch("commits.get_code_files_for_review", return_value=changed),
        ):
            return pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, "git commit -m 'fix'", _CWD
            )

    def test_fixes_confined_to_the_reviewed_set_are_not_blocked(self):
        """The loop, closed: the reviewed work landed and cleared the flag, and
        these are the fixes that review produced."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py", "b.py"])
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")

        self._gate(["a.py", "b.py"])

    def test_the_commit_after_that_is_blocked_again(self):
        """Coverage is spent once. Without this the exemption never ends."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py", "b.py"])
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-2")

        with self.assertRaises(_common.BlockedError) as ctx:
            self._gate(["a.py", "b.py"])
        self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_new_work_alongside_the_fixes_still_blocks(self):
        """Coverage forgives the review's own files, never work smuggled in
        beside them."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py", "b.py"])
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")

        with self.assertRaises(_common.BlockedError):
            self._gate(["a.py", "b.py", "new1.py", "new2.py"])

    def test_no_coverage_blocks_as_before(self):
        """Non-vacuity for the whole class: the gate still gates."""
        with self.assertRaises(_common.BlockedError):
            self._gate(["a.py", "b.py"])


class TestCoverageBelongsToTheRepoItWasMeasuredIn(_HookTestCase):
    """Coverage holds repo-relative PATHS, so it is keyed on the repo — the
    same key the watermark uses. Under the session key, the identical relative
    paths in another checkout would have matched by name and exempted files no
    review ever opened."""

    _OTHER = "worktree-story-cov"

    def test_the_recorder_keys_on_the_repo_the_review_ran_in(self):
        with patch("commits.get_code_files_for_review", return_value=["a.py"]):
            subagent_stop.run(
                {
                    "session_id": "t",
                    "agent_id": "rev-1",
                    "agent_type": "xp-agents:xp-code-reviewer",
                    "cwd": f"/x/{self._OTHER}/repo",
                    "last_assistant_message": "Done",
                },
                smm_dir=self.smm_dir,
            )

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, self._OTHER), {"a.py"}
        )
        self.assertEqual(review_records.read_review_coverage(self.smm_dir, _KEY), set())

    def test_a_commit_landing_in_another_repo_is_not_forgiven(self):
        """`git -C <other-repo> commit` after a review of THIS checkout. The
        two file sets share path names and nothing else."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py", "b.py"])
        review_records.end_review_cycle(self.smm_dir, _KEY, _KEY, "sha-1")

        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / self._OTHER
            other.mkdir()
            with (
                patch("commits.get_staged_diff", return_value=""),
                patch("commits.get_staged_files", return_value=[]),
                patch(
                    "commits.get_code_files_for_review", return_value=["a.py", "b.py"]
                ),
                self.assertRaises(_common.BlockedError) as ctx,
            ):
                pre_tool_bash_commit_gates.commit_gate_parts(
                    self.smm_dir, f"git -C {other} commit -m 'fix'", _CWD
                )
        # The REVIEW gate, not the unreachable-target refusal above it.
        self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_ageing_spends_the_repo_that_committed(self):
        """end_review_cycle ages under the WATERMARK key, so a commit in one
        repo cannot spend another repo's coverage."""
        review_records.write_review_coverage(self.smm_dir, _KEY, ["a.py"])

        review_records.end_review_cycle(self.smm_dir, self._OTHER, _KEY, "sha-1")
        review_records.end_review_cycle(self.smm_dir, self._OTHER, _KEY, "sha-2")

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, _KEY), {"a.py"}
        )


if __name__ == "__main__":
    unittest.main()
