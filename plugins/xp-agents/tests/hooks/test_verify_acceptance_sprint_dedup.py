#!/usr/bin/env python3
"""`--sprint` runs each DISTINCT command once, and still reports every row.

Stories share acceptance commands — the "full suite green" E2E criterion is
declared by nearly every story, so one sprint enumerated 21 items of which 9
were the identical whole-suite run. Re-running it 9 times against one unchanging
tree cannot produce 9 different answers; it just spends the batch budget, and
that budget SKIPS items deterministically in sprint order once exhausted, so the
duplication does not merely cost time — it can push genuine, distinct checks
into `skipped` and out of the verified set.

The split that matters: dedupe EXECUTION, not REPORTING. Every (story, ac) pair
keeps its own row, because the matrix is how a reader sees which stories are
covered and the close gate counts failures per item. Collapsing rows would hide
stories; collapsing runs hides nothing, since the command and the tree are
identical by construction.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import verify_acceptance_record


class TestDistinctCommands(unittest.TestCase):
    """The enumeration the runner drives its subprocess calls from."""

    def test_a_command_two_stories_share_is_enumerated_once(self):
        items = [
            ("story-001", None, None, "pytest -n auto", False),
            ("story-002", None, None, "pytest -n auto", False),
            ("story-003", None, None, "pytest tests/x.py", False),
        ]

        self.assertEqual(
            verify_acceptance_record.distinct_commands(items),
            ("pytest -n auto", "pytest tests/x.py"),
        )

    def test_first_appearance_order_is_kept(self):
        """Sprint order is what the batch budget skips in, so the run order the
        budget consumes must stay the order the stories declared."""
        items = [
            ("story-001", None, None, "b", False),
            ("story-002", None, None, "a", False),
            ("story-003", None, None, "b", False),
        ]

        self.assertEqual(verify_acceptance_record.distinct_commands(items), ("b", "a"))

    def test_manual_sentinels_contribute_no_command(self):
        """An N/A row is never shelled, so it must not enter the run set — and
        its command is None, which would crash a subprocess call."""
        items = [
            ("story-001", None, None, None, True),
            ("story-002", None, None, "pytest", False),
        ]

        self.assertEqual(verify_acceptance_record.distinct_commands(items), ("pytest",))

    def test_no_runnable_commands_is_an_empty_run_set(self):
        items = [("story-001", None, None, None, True)]

        self.assertEqual(verify_acceptance_record.distinct_commands(items), ())


class TestEveryRowStillReported(unittest.TestCase):
    """Dedupe execution, not reporting: a story whose command another story
    already ran is still verified, and must still appear."""

    def test_both_sharers_get_a_row_carrying_the_one_result(self):
        results = {"pytest -n auto": {"returncode": 0}}
        items = [
            ("story-001", None, "cli", "pytest -n auto", False),
            ("story-002", 2, None, "pytest -n auto", False),
        ]

        rows = verify_acceptance_record.rows_from_results(items, results)

        self.assertEqual([r["story"] for r in rows], ["story-001", "story-002"])
        self.assertEqual([r["returncode"] for r in rows], [0, 0])
        self.assertEqual(rows[0]["surface"], "cli")
        self.assertEqual(rows[1]["ac_idx"], 2)

    def test_a_shared_failure_fails_every_row_that_named_it(self):
        """The close gate counts failing ITEMS. A red shared command must not
        report red once and green for the rest — every story that declared it
        is equally unverified."""
        results = {"x": {"returncode": 1, "output": "boom"}}
        items = [
            ("story-001", None, None, "x", False),
            ("story-002", None, None, "x", False),
        ]

        rows = verify_acceptance_record.rows_from_results(items, results)

        self.assertEqual([r["returncode"] for r in rows], [1, 1])
        self.assertEqual([r["output"] for r in rows], ["boom", "boom"])

    def test_a_manual_row_is_reported_without_a_returncode(self):
        rows = verify_acceptance_record.rows_from_results(
            [("story-001", None, None, None, True)], {}
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["na"])
        self.assertNotIn("returncode", rows[0])

    def test_a_command_the_budget_never_ran_reports_skipped_for_each_sharer(self):
        """Absent from *results* means the batch budget stopped before it
        started. That is neither pass nor fail, and both sharers must say so
        rather than one silently vanishing from the matrix."""
        items = [
            ("story-001", None, None, "never-ran", False),
            ("story-002", None, None, "never-ran", False),
        ]

        rows = verify_acceptance_record.rows_from_results(items, {})

        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["skipped"])
            self.assertNotIn("returncode", row)


if __name__ == "__main__":
    unittest.main()
