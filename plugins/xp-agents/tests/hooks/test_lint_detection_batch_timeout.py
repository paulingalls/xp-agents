#!/usr/bin/env python3
"""run_linter_batch's scaled timeout, and bash-failure concern content.

Split from test_lint_detection.py to keep files under the 500-line cap.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import lint_check
from concerns import TEST_CONCERN_RE
from conftest import _HookTestCase, _mock_ruff_result
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

_WATERMARK_ID = "test-lint-detection"


class TestRunLinterBatchScaledTimeout(unittest.TestCase):
    """run_linter_batch timeout scales with len(eligible) per story-007.

    Formula: ``min(CAP, BATCH_BASE + PER_PATH * N)`` — small batches get one
    base interval, large batches stay bounded by CAP so a hung linter can't
    stall the commit gate forever. The empty-on-timeout sentinel contract is
    pinned by test_lint.TestRunLinterBatch.
    """

    def _captured_timeout(self, n_paths: int) -> float:
        paths = [f"f{i}.py" for i in range(n_paths)]
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", paths, cwd="/tmp")
        return float(mock_run.call_args.kwargs["timeout"])

    def _expected(self, n: int) -> float:
        return min(
            lint_check.BATCH_TIMEOUT_CAP_S,
            lint_check.BATCH_TIMEOUT_BASE_S + lint_check.BATCH_TIMEOUT_PER_PATH_S * n,
        )

    def test_batch_budget_is_not_the_edit_time_budget(self):
        """The batch budget must be materially larger than the edit-time one,
        because the two have OPPOSITE failure semantics.

        An edit-time timeout returns None: no nudge, nobody blocked. A batch
        timeout is `unverified`, and the commit gate fails CLOSED on it — it
        BLOCKS. Sharing one 5s number was safe only while the batch ran ruff and
        nothing else; the gate now dispatches per the linter table, so the batch
        runs `npx eslint`, `golangci-lint run`, `dart analyze` — tools whose cold
        start alone (npx bin resolution, a TS program build, package type-check)
        routinely exceeds 5s on a real repo.

        A timeout is also the ONE unverified cause the agent cannot act on: it
        cannot make golangci-lint faster. Too small a budget therefore blocks
        every commit in that ecosystem, unfixably — the exact failure the
        project-scoped DEGRADE row exists to avoid, arriving through a different
        door. Budget for a real linter; the CAP still bounds a hung one.
        """
        self.assertGreater(
            lint_check.BATCH_TIMEOUT_BASE_S,
            lint_check.LINTER_BASE_TIMEOUT_S,
            "commit-gate batch budget must not inherit the edit-time per-file one",
        )
        self.assertGreaterEqual(
            self._captured_timeout(1),
            30.0,
            "a one-file commit must budget for a real linter's cold start",
        )

    def test_batch_cap_stays_inside_the_harness_hook_budget(self):
        """And the budget has a CEILING, for the opposite reason.

        The gate only blocks because the hook exits 2. A hook the HARNESS kills
        for overrunning its own timeout (60s default; pre_tool_bash registers no
        override) exits no such thing — so a batch that outlives the harness does
        not fail closed, it fails OPEN, and the commit sails through unlinted.
        That is strictly worse than the block the larger budget exists to avoid.

        So the CAP is bounded on BOTH sides, and this is the side you cannot see
        in a test of the linter alone. Leave headroom for the rest of the hook
        (tier-1 diff scan, git forks, SMM loads). Raising the CAP past this means
        raising the hook's registered timeout FIRST.
        """
        self.assertLessEqual(
            lint_check.BATCH_TIMEOUT_CAP_S,
            45.0,
            "a batch that outlives the harness hook timeout fails OPEN, not closed",
        )

    def test_n1_below_cap(self):
        self.assertAlmostEqual(self._captured_timeout(1), self._expected(1), places=6)

    def test_n20_below_cap(self):
        self.assertAlmostEqual(self._captured_timeout(20), self._expected(20), places=6)

    def test_at_cap_boundary(self):
        # N=100 with default constants saturates the min() to the literal cap.
        self.assertEqual(self._captured_timeout(100), lint_check.BATCH_TIMEOUT_CAP_S)

    def test_above_cap_clamped(self):
        self.assertEqual(self._captured_timeout(500), lint_check.BATCH_TIMEOUT_CAP_S)

    def test_uses_eligible_not_input_count(self):
        """Non-.py paths are filtered out before scaling — the timeout
        sizes against what ruff actually sees, not the raw input list."""
        paths = ["a.py"] + [f"x{i}.md" for i in range(19)]
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", paths, cwd="/tmp")
        self.assertAlmostEqual(
            float(mock_run.call_args.kwargs["timeout"]),
            self._expected(1),
            places=6,
        )


class TestBashFailureConcernContent(_HookTestCase):
    """Test failure concern events should be concise, not full pytest output."""

    def test_test_failure_concern_is_summary(self):
        """Concern should identify test file, not dump full traceback."""
        bash_failure.run(
            {
                "session_id": "t",
                "tool_input": {
                    "command": "cd /foo && uv run pytest tests/test_bar.py -v"
                },
                "error": (
                    "Exit code 1\n"
                    "===== test session starts =====\n"
                    "FAILED tests/test_bar.py::test_thing - AssertionError\n"
                    "===== 1 failed, 2 passed =====\n"
                ),
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        content = concerns[0]["content"]
        # The gate reads concerns through TEST_CONCERN_RE, so that — not any
        # one prefix — is the contract. This command is compound, and its
        # payload corroborates real counts, so the concern reports those
        # ("Test failures detected: 1 failed") rather than a bare exit code.
        self.assertRegex(content, TEST_CONCERN_RE)
        self.assertNotIn("test session starts", content)
        self.assertLess(len(content), 200)


if __name__ == "__main__":
    unittest.main()
