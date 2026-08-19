#!/usr/bin/env python3
"""A git read that never ANSWERED is not git answering "no".

Its own file, beside `test_commit_observer.py`'s claims/refusals/costs, because
this suite is about one distinction rather than about the observer's boundary:
`commits._run_git` collapsed a timeout, a missing binary and a non-zero exit
into a single `None`, so a 5s range-walk timeout reached `_reconcile` as "the
last-seen commit is unknown to this checkout" — a concern naming a rebase that
never happened, followed by an advance past a range whose commits are then never
recorded, whose resolve trailers never link, and whose work the review watermark
never covers.

The two directions cost opposite things and both are pinned here: a timeout
treated as permanent loses the range for good, while a permanent failure treated
as retryable re-forks the same read on every Bash, forever. The losing direction
is the unbounded retry, so everything except a timeout keeps declining.

Driven by a scoped PATH shim rather than by patching `subprocess.run` to raise:
patching the exception asserts only that the `except` clause does what it was
just written to do. See `_observer_case.stalling_git_path` for why the shim is
scoped to the range walk's own argument and not to git as a whole.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import merged_range
from _observer_case import ORDINARY_BASH, _ObserverCase
from conftest import _make_bash_input

_POST_TOOL_HOOK = Path(__file__).parent.parent.parent / "scripts" / "bash_post_tool.py"


class TestARetryableFailureIsNotARewrite(_ObserverCase):
    """One row per failure shape git can hand the range walk, and what the
    observer must do with each. The module docstring above says why."""

    def test_a_timed_out_range_walk_reports_nothing_and_is_retried(self):
        """The whole defect, end to end: no concern, no advance, and the range
        recorded by the next observe once git can answer again."""
        self.seed_observer()
        seeded = self.marker()
        landed = self.commit("feat: x")

        with (
            patch.object(merged_range, "_TIMEOUT_SECONDS", 0.5),
            self.stalling_git(),
        ):
            self.observe()

        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.concerns(), [])
        self.assertEqual(self.marker(), seeded)

        self.observe()

        self.assertEqual(self.recorded_hashes(), [landed])
        self.assertEqual(self.marker(), {"head": landed})

    def test_a_base_this_repo_never_had_still_declines_and_advances(self):
        """The other direction, paired with the case above so the two cannot
        collapse back into one path: git RAN and refused, which is permanent, so
        the decline and its concern stand and the marker advances past them."""
        markers.marker_write(
            self.smm_dir, markers.LAST_SEEN_HEAD, {"head": "0" * 40}, "main"
        )
        head = self.commit("feat: x")

        self.observe()

        self.assertEqual(self.commit_events(), [])
        self.assertIn("unknown to this checkout", self.concerns()[0]["content"])
        self.assertEqual(self.marker(), {"head": head})

    def test_no_git_on_path_declines_rather_than_retrying_forever(self):
        """`FileNotFoundError` is an `OSError`, and mapping the whole class to
        the retryable path would leave a git-less checkout never advancing its
        marker and re-forking the walk on every Bash for the rest of the
        session. `git_head.read_head` is a plain file read, so no git on PATH
        does not short-circuit `observe` before it gets here."""
        self.seed_observer()
        head = self.commit("feat: x")

        with self.no_git():
            self.observe()

        self.assertEqual(self.commit_events(), [])
        self.assertIn("unknown to this checkout", self.concerns()[0]["content"])
        self.assertEqual(self.marker(), {"head": head})

    def test_the_hook_survives_a_stalled_range_walk(self):
        """As a SUBPROCESS, because exit status is the whole assertion and an
        in-process call cannot observe it. `bash_post_tool` calls `observe`
        with no try/except, so routing the timeout down the existing raise path
        would leave `run()`, exit non-zero with a traceback, and kill test-run
        detection, both commit nudges and the TDD signals for that call — while
        an in-process `assertRaises` row looks perfectly correct. This one pays
        the real range-walk bound in wall time; there is no way to patch a
        constant into another process without shipping an env knob.
        """
        self.seed_observer()
        self.commit("feat: x")
        payload = _make_bash_input(command=ORDINARY_BASH, cwd=str(self.repo))

        result = subprocess.run(
            [sys.executable, str(_POST_TOOL_HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": self.stalling_git_path()},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
