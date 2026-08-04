#!/usr/bin/env python3
"""Throwaway: validity checks for the commit-shape coverage probe.

The probe's output is story-004's evidence for no-go criterion 3, so a wrong
cell is a wrong verdict. Every check here fails against a specific
plausible-but-wrong implementation, named in its comment.

The load-bearing ones are the two ways this probe could lie in the SAME
direction the criterion is measured in:

1. **An unarmed rig reports every shape as not-blocked**, which is
   indistinguishable from a total gate bypass. The gate SKIPS ITSELF SILENTLY
   when the SMM fails to validate (`pre_tool_bash.py:240` guards the whole
   commit-gate call on `smm_dir is not None`), and nothing in the hook's output
   says so. A positive control is the only honest guard.
2. **A crashing hook looks permissive.** `blocked = (rc == 2)` reads a
   traceback, an import error, or a missing interpreter as "the gate allowed
   this command".

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_commit_shapes.py
(`pytest.ini` sets `testpaths` to the tests dir, so the default run skips it.)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import probe_commit_shapes as probe

BLOCKED = probe.BLOCKED
ALLOWED = probe.ALLOWED
ERROR = probe.ERROR


class _RigTestCase(unittest.TestCase):
    """Builds the one fixture every check needs: an armed gate.

    Armed means all three of cadence `commit` (the default), no recorded
    review, and at least `REVIEW_CYCLE_THRESHOLD` staged code files. Miss any
    one and the gate allows every shape for a reason that has nothing to do
    with the shape.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo, self.smm_dir = probe.build_rig(root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, command: str) -> dict:
        return probe.run_shape(command, repo=self.repo, smm_dir=self.smm_dir)


class TestTheRigIsArmed(_RigTestCase):
    def test_the_control_shape_blocks(self) -> None:
        # If this fails, nothing else in the file means anything: an unarmed
        # gate allows every shape. Pinned as its own check so the failure names
        # the rig rather than the shape under test.
        result = self._run('git commit -m "probe control"')
        self.assertEqual(result["classification"], BLOCKED)
        self.assertIn("/xp-quality-review", result["stderr"])

    def test_assert_armed_raises_when_the_control_does_not_block(self) -> None:
        # The whole point. Guards a probe that reports a matrix regardless —
        # which, on an unvalidatable SMM, is 15 rows of "not blocked" that read
        # exactly like criterion 3 failing, and would be reported as the
        # verdict. An SMM dir that cannot validate is the realistic way in.
        with (
            tempfile.TemporaryDirectory() as td,
            self.assertRaises(probe.RigNotArmedError),
        ):
            probe.assert_armed(repo=self.repo, smm_dir=Path(td) / "absent")

    def test_assert_armed_passes_on_the_real_rig(self) -> None:
        probe.assert_armed(repo=self.repo, smm_dir=self.smm_dir)


class TestClassification(unittest.TestCase):
    def test_exit_two_with_a_reason_is_blocked(self) -> None:
        self.assertEqual(probe.classify(2, "Run /xp-quality-review"), BLOCKED)

    def test_exit_zero_is_allowed(self) -> None:
        self.assertEqual(probe.classify(0, ""), ALLOWED)

    def test_any_other_exit_status_is_an_error_not_allowed(self) -> None:
        # Guards `blocked = (rc == 2)`, which folds every crash into ALLOWED.
        # A hook that dies on an import error would then be recorded as a
        # bypassable shell path — a false criterion-3 failure.
        for rc in (1, 3, 127, -9):
            with self.subTest(rc=rc):
                self.assertEqual(probe.classify(rc, "Traceback..."), ERROR)

    def test_exit_two_with_no_reason_is_an_error(self) -> None:
        # A block is only a block if it carries the reason AC-1 asks for.
        # Exit 2 with empty stderr is a broken gate, not an enforced one.
        self.assertEqual(probe.classify(2, "   "), ERROR)


class TestObservedShapes(_RigTestCase):
    def test_shapes_the_detector_catches_are_reported_blocked(self) -> None:
        for command in (
            'git commit -m "x"',
            'env FOO=1 git commit -m "x"',
            'git add -A && git commit -m "x"',
            'git -c user.name=x commit -m "x"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self._run(command)["classification"], BLOCKED)

    def test_shapes_the_detector_misses_are_reported_not_blocked(self) -> None:
        # These are the finding, not a bug in the probe. Pinned so a later
        # change to the detector shows up here as a diff rather than silently
        # altering the matrix story-007 quotes.
        for command in (
            'sh -c "git commit -m x"',
            "sh -c 'git commit -m x'",
            "git ci -m x",
        ):
            with self.subTest(command=command):
                self.assertEqual(self._run(command)["classification"], ALLOWED)

    def test_a_non_commit_command_is_allowed(self) -> None:
        # Control in the other direction: the gate must not block everything.
        # A probe whose rig blocks unconditionally would pass every check above.
        self.assertEqual(self._run("ls -la")["classification"], ALLOWED)

    def test_the_block_reason_is_captured_verbatim(self) -> None:
        # AC-1 says blocked-with-OUR-reason. Only `str(e)` reaches stderr —
        # BlockedError's system_message is built and dropped on this path — so
        # the recorded reason must be the stderr text exactly, not a summary.
        result = self._run('git commit -m "x"')
        self.assertTrue(
            result["stderr"].startswith("Run /xp-quality-review before committing"),
            result["stderr"],
        )
        self.assertIn("code files changed since last review", result["stderr"])


class TestQuotedDashCSignature(_RigTestCase):
    """The story-011 bypass, as this probe observes it.

    Not a fix and not a duplicate record — concern `6c5d02b11cda` owns it. What
    belongs here is the observable signature, so criterion 3's matrix reports
    it as a measured row rather than an anecdote: the same command blocks
    unquoted and does not block quoted.
    """

    def test_unquoted_dash_c_blocks_but_quoted_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            other, _ = probe.build_rig(Path(td), stage_files=False)
            unquoted = self._run(f"git -C {other} commit -m x")
            quoted = self._run(f'git -C "{other}" commit -m x')
        # Unquoted: the parse sees the path, targets the empty repo, nothing
        # staged there, so the review gate has nothing to count.
        self.assertEqual(unquoted["classification"], ALLOWED)
        # Quoted: the parse cannot see the path and silently falls back to the
        # hook's cwd -- THIS repo, which has staged files -- so it blocks. The
        # asymmetry is the bug's fingerprint: the gate's answer depends on
        # quoting, meaning it scanned a repo the commit was never going to.
        self.assertEqual(quoted["classification"], BLOCKED)


class TestRender(_RigTestCase):
    def test_every_shape_gets_a_row_and_errors_are_visible(self) -> None:
        results = [
            {
                "name": "plain",
                "command": "git commit",
                "classification": BLOCKED,
                "stderr": "Run /xp-quality-review",
                "returncode": 2,
            },
            {
                "name": "wrapped",
                "command": 'sh -c "git commit"',
                "classification": ALLOWED,
                "stderr": "",
                "returncode": 0,
            },
            {
                "name": "broken",
                "command": "git commit",
                "classification": ERROR,
                "stderr": "Traceback",
                "returncode": 1,
            },
        ]
        md = probe.render(results)
        for needle in ("plain", "wrapped", "broken", BLOCKED, ALLOWED, ERROR):
            with self.subTest(needle=needle):
                self.assertIn(needle, md)

    def test_render_refuses_an_empty_result_set(self) -> None:
        # An empty matrix renders as a well-formed table with no rows, which
        # reads as "no shape bypasses the gate" -- the confident lie the
        # tabulator's empty-corpus guard exists to prevent, one story later.
        with self.assertRaises(ValueError):
            probe.render([])


if __name__ == "__main__":
    unittest.main()
