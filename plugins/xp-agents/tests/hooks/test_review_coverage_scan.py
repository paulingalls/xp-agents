#!/usr/bin/env python3
"""What the coverage scan reads, and what it costs — measured, not mocked.

Split from test_review_coverage.py, which pins the coverage RECORD and the
gate arithmetic over it. Every test there patches `get_code_files_for_review`,
which is right for testing set arithmetic and is exactly why v5.17.0's defect
survived a green suite: all of them pass against a recorder that asks git the
wrong question.

These do not patch it. Each runs a real reviewer completion against a real git
repo, so the legs actually run — which is what makes them able to fail on WHAT
the scan reads (the reviewer's own unstaged and untracked fixes) and on what it
SPENDS (five git reads inside a 5s hook budget).
"""

import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _repo_fixtures as repo_fixtures
import identity
import review_records
import subagent_stop
from conftest import _HookTestCase


class _RealTreeCase(_HookTestCase):
    """A real git repo with two committed code files, and a reviewer that
    stops in it. Shared by the two classes below that must not patch the scan
    — one measures WHAT it reads, the other what it COSTS, and both need the
    legs to actually run."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        repo_fixtures.init_repo(self.repo)
        Path(self.repo, "a.py").write_text("x = 1\n")
        Path(self.repo, "b.py").write_text("y = 1\n")
        repo_fixtures.git_in(self.repo, "add", "-A")
        repo_fixtures.git_in(self.repo, "commit", "-m", "base")
        self.key = identity.review_watermark_key(self.repo)
        self.addCleanup(self._tmp.cleanup)

    def _stop_reviewer(self) -> None:
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "rev-1",
                "agent_type": "xp-agents:xp-code-reviewer",
                "cwd": self.repo,
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )


class TestTheScopeIsMeasuredAgainstARealTree(_RealTreeCase):
    """What the scan actually reads, against a tree it did not choose.

    The contrast is with test_review_coverage.py, not with this file — no test
    HERE patches the scan. Every test THERE hands the recorder its answer, which
    is right for pinning set arithmetic and is exactly how v5.17.0 shipped a
    coverage record that is empty in the dominant flow: the reviewer's fixes are
    UNSTAGED when it stops, and the scan read staged + committed only.

    Unstaged is not an edge case here, it is the normal state. The reviewer
    edits files and returns; nothing stages them. And they are exactly the
    files the exemption exists to forgive — so an empty set means the next
    `git add -A && git commit` counts them unreviewed and demands another
    review, whose fixes demand another. The review the preload hands it is the
    working-tree diff (`git diff HEAD`, staged and unstaged both), so a scope
    that omits unstaged work is also narrower than what was actually reviewed.
    """

    def _reviewer_stops(self) -> set[str]:
        self._stop_reviewer()
        return review_records.read_review_coverage(self.smm_dir, self.key)

    def test_the_reviewers_own_unstaged_fix_is_covered(self):
        """The dominant flow, and the one v5.17.0 missed."""
        Path(self.repo, "a.py").write_text("x = 2\n")

        self.assertEqual(self._reviewer_stops(), {"a.py"})

    def test_staged_and_unstaged_fixes_are_both_covered(self):
        """A reviewer that staged some of its edits and not others — the set is
        the union, not whichever half the scan happens to read."""
        Path(self.repo, "a.py").write_text("x = 2\n")
        repo_fixtures.git_in(self.repo, "add", "a.py")
        Path(self.repo, "b.py").write_text("y = 2\n")

        self.assertEqual(self._reviewer_stops(), {"a.py", "b.py"})

    def test_an_untouched_tree_still_covers_nothing(self):
        """The widening must not become a blanket exemption: a review that
        changed nothing forgives nothing, so the gate is unaffected."""
        self.assertEqual(self._reviewer_stops(), set())

    def test_a_file_the_reviewer_CREATED_is_covered(self):
        """`git diff` lists a created file at no stage, staged or not, so the
        unstaged leg alone recorded nothing for the test a reviewer writes —
        the same defect as v5.17.0's, for additions instead of edits. The next
        `git add -A` stages it and the gate then counts it unreviewed."""
        Path(self.repo, "test_new.py").write_text("def test_x():\n    pass\n")

        self.assertEqual(self._reviewer_stops(), {"test_new.py"})

    def test_ignored_output_is_not_mistaken_for_created_work(self):
        """`--exclude-standard`, or the created-files leg hands back every build
        artefact in the tree and the exemption stops meaning anything."""
        Path(self.repo, ".gitignore").write_text("build/\n")
        repo_fixtures.git_in(self.repo, "add", ".gitignore")
        repo_fixtures.git_in(self.repo, "commit", "-m", "ignore build")
        Path(self.repo, "build").mkdir()
        Path(self.repo, "build", "generated.py").write_text("x = 1\n")

        self.assertEqual(self._reviewer_stops(), set())

    def test_a_file_the_reviewer_left_alone_is_not_covered(self):
        """Membership, not just count — the assertion a set-size check would
        pass while exempting the wrong file."""
        Path(self.repo, "a.py").write_text("x = 2\n")

        self.assertNotIn("b.py", self._reviewer_stops())


class TestTheScanFitsTheHookBudget(_RealTreeCase):
    """The recorder's git reads must fit the budget the hook is given.

    `_run_git` allows 5s PER CALL and `hooks.json` gives SubagentStop 5000ms
    TOTAL, so one slow read could spend the whole allowance and the rest could
    not run at all. The handler makes five: four scan legs (staged, the watermark
    range, unstaged, created) plus the HEAD read that stamps the record. A
    handler killed part-way leaves the gate armed with no flag, whose only
    recovery is another full review.

    Measured on a real repo so every leg actually runs: at `/tmp` the first
    read fails and the scan returns early, and the sum would understate the
    worst case by most of it.

    Asserted as the SUM against the declared budget rather than as a literal
    per-call number, so the pin follows the budget and the read count instead
    of having to be re-derived by hand when either moves.
    """

    _HOOK_BUDGET_S = 5.0
    _EXPECTED_READS = 5

    def _timeouts_during_a_completion(self) -> list[float]:
        """Each git read's timeout, an absent one recorded as `inf`.

        `inf` is what an unbounded call is worth against a budget, so the sum
        below fails on one without needing a separate None check — and the list
        stays a list of floats, which is what a reader assumes when they see it
        summed."""
        seen: list[float] = []
        real = subprocess.run

        def spy(args, **kwargs):
            if args and args[0] == "git":
                seen.append(float(kwargs.get("timeout") or math.inf))
            return real(args, **kwargs)

        head = repo_fixtures.git_in(self.repo, "rev-parse", "HEAD").strip()
        review_records.write_review_watermark(self.smm_dir, self.key, head)
        Path(self.repo, "a.py").write_text("x = 2\n")
        with patch("commits.subprocess.run", side_effect=spy):
            self._stop_reviewer()
        return seen

    def test_every_read_the_handler_makes_is_counted(self):
        """The non-vacuity pin: a sum under budget is trivially satisfied by a
        scan that stopped early, which is what made the first draft of this
        pass against the very code it was written to fail. It also fails when a
        read is ADDED without being paid for — which is how the HEAD read that
        stamps the coverage record got a bound instead of the 5s default."""
        self.assertEqual(
            len(self._timeouts_during_a_completion()), self._EXPECTED_READS
        )

    def test_every_read_is_bounded(self):
        seen = self._timeouts_during_a_completion()

        self.assertTrue(seen, "no git read observed — the spy missed the scan")
        self.assertNotIn(math.inf, seen, "an unbounded git read can hang the hook")

    def test_the_worst_case_leaves_room_to_finish(self):
        """Worst case is every read timing out. The writes come after them, so
        the budget has to cover the scan with room left, not merely equal it."""
        seen = self._timeouts_during_a_completion()

        self.assertLess(sum(seen), self._HOOK_BUDGET_S)


class TestCoverageExpiresOnCommitsThatMissTheCommitSites(_RealTreeCase):
    """Ageing is write-driven, and some commits never reach the writer.

    `_age_review_coverage` runs only from `end_review_cycle`, reached from the
    PostToolUse:Bash commit handlers and the close merge. A commit that lands
    without passing one — an xp- subagent's, which `is_xp_agent` skips — never
    spends the record, so its paths stay exempt with no bound at all. A later
    session can then rewrite every file the review once glanced at and commit
    unreviewed, because `uncovered_count` returns 0. Fail-open in the gate.

    A read-time counter cannot close it: the write that fails to age is the
    same one that fails to advance the watermark, so nothing in the SMM moved
    and there is nothing to count. What DID move is HEAD, so the record carries
    the commit it was written at and the read asks git how far the branch has
    travelled since. Measured against a real repo for that reason — the check
    has no meaning without one.
    """

    def _cover_a_py(self) -> None:
        Path(self.repo, "a.py").write_text("x = 2\n")
        self._stop_reviewer()

    def _commit_behind_the_gates(self, message: str) -> None:
        """A commit that reaches NO commit site — the xp- subagent's shape."""
        Path(self.repo, "b.py").write_text(f"# {message}\n")
        repo_fixtures.git_in(self.repo, "add", "-A")
        repo_fixtures.git_in(self.repo, "commit", "-m", message)

    def _coverage(self) -> set[str]:
        return review_records.read_review_coverage(
            self.smm_dir, self.key, cwd=self.repo
        )

    def test_coverage_survives_the_first_such_commit(self):
        """The control, and it is the case the exemption exists for: the
        reviewed work lands, and the fixes still have their cover."""
        self._cover_a_py()

        self._commit_behind_the_gates("first")

        self.assertEqual(self._coverage(), {"a.py"})

    def test_coverage_expires_by_the_second(self):
        self._cover_a_py()

        self._commit_behind_the_gates("first")
        self._commit_behind_the_gates("second")

        self.assertEqual(self._coverage(), set())

    def test_an_unmoved_head_spends_nothing(self):
        """No commit landed at all, so the record is untouched — the read must
        not age anything by merely being called."""
        self._cover_a_py()

        self.assertEqual(self._coverage(), {"a.py"})
        self.assertEqual(self._coverage(), {"a.py"})

    def test_a_base_merge_is_one_landing_and_not_the_range_it_carried(self):
        """`rev-list --count` counts everything reachable, so a `git merge <base>`
        bringing three commits read as four landings and threw away a review just
        earned — the loop this record exists to break, entered from the other
        side. `--first-parent` counts what landed on THIS line."""
        start = repo_fixtures.git_in(self.repo, "rev-parse", "HEAD").strip()
        repo_fixtures.git_in(self.repo, "checkout", "-q", "-b", "base-work")
        for i in range(3):
            Path(self.repo, f"base{i}.py").write_text("1\n")
            repo_fixtures.git_in(self.repo, "add", "-A")
            repo_fixtures.git_in(self.repo, "commit", "-m", f"base{i}")
        repo_fixtures.git_in(self.repo, "checkout", "-q", "-B", "work", start)

        self._cover_a_py()
        repo_fixtures.git_in(self.repo, "merge", "--no-ff", "-m", "merge", "base-work")

        self.assertEqual(self._coverage(), {"a.py"})

    def test_a_caller_with_no_repo_reads_the_record_as_it_stands(self):
        """The check needs git, and callers that have no cwd to offer keep the
        old behaviour rather than losing their coverage to an unanswerable
        question."""
        self._cover_a_py()
        self._commit_behind_the_gates("first")
        self._commit_behind_the_gates("second")

        self.assertEqual(
            review_records.read_review_coverage(self.smm_dir, self.key), {"a.py"}
        )


if __name__ == "__main__":
    unittest.main()
