#!/usr/bin/env python3
"""Tests for worktree_teardown.py: the mirror image of worktree_bootstrap.

A teammate worktree can start things that outlive it (e.g. a docker compose
stack); `stack.worktree_teardown` lets a project declare a command to stop
them before the worktree is removed. Unlike bootstrap, teardown must NEVER
raise — cleanup that refuses to clean up is worse than the leak it prevents
(decision `74662df6641d`, topic `teardown-degrades-quiet`).

Every test asserts the command's EFFECT (a file it wrote), never merely that
a runner was called, following the rule pinned in
test_spawn_teammate_bootstrap.py.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree_teardown
from _bases import _SMMTestCase
from _system_context_fixtures import valid_doc, write_doc


class _TeardownTestCase(_SMMTestCase):
    """Shared setup: a temp SMM dir whose system_context may declare a
    teardown, and a temp dir standing in for a worktree path."""

    def setUp(self):
        super().setUp()
        self.wt_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.wt_dir, ignore_errors=True)
        super().tearDown()

    def declare_teardown(self, command: str) -> None:
        doc = valid_doc()
        doc["stack"]["worktree_teardown"] = command
        write_doc(self.smm_dir, doc)


class TestTeardownRuns(_TeardownTestCase):
    """AC1: a declared command runs, with the worktree path as cwd."""

    def test_declared_command_effect_is_observable_in_the_worktree(self):
        self.declare_teardown("echo torn > torn.txt")

        worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        artifact = self.wt_dir / "torn.txt"
        self.assertTrue(artifact.is_file())
        self.assertEqual(artifact.read_text().strip(), "torn")

    def test_command_runs_with_the_worktree_as_cwd(self):
        self.declare_teardown("pwd > where.txt")

        worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        recorded = (self.wt_dir / "where.txt").read_text().strip()
        self.assertEqual(Path(recorded).resolve(), self.wt_dir.resolve())


class TestTeardownAbsent(_TeardownTestCase):
    """AC2: no declaration is a no-op that spawns nothing."""

    def test_no_worktree_teardown_field_spawns_nothing(self):
        write_doc(self.smm_dir, valid_doc())

        with patch.object(
            worktree_teardown._subprocess_env, "run_in_new_process_group"
        ) as spawn:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        spawn.assert_not_called()

    def test_no_system_context_spawns_nothing(self):
        (self.smm_dir / "system_context.json").unlink(missing_ok=True)

        with patch.object(
            worktree_teardown._subprocess_env, "run_in_new_process_group"
        ) as spawn:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        spawn.assert_not_called()


class TestTeardownDegradesQuiet(_TeardownTestCase):
    """AC3: failures return normally and report the reason on stderr."""

    def test_nonzero_exit_returns_normally_and_reports(self):
        self.declare_teardown("echo half > half.txt; echo boom >&2; exit 1")

        with patch("sys.stderr") as mock_stderr:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        self.assertTrue((self.wt_dir / "half.txt").is_file())
        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("boom", written)
        self.assertIn("1", written)

    def test_timeout_returns_normally_and_reports(self):
        self.declare_teardown("sleep 5")

        with (
            patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}),
            patch("sys.stderr") as mock_stderr,
        ):
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("timed out", written)

    def test_corrupt_system_context_returns_normally_and_reports(self):
        # A corrupt context must not read as "this project declared no
        # teardown". Those two states are indistinguishable to the caller
        # unless the corrupt one SAYS something: the operator whose declared
        # teardown silently stopped running otherwise has no signal at all,
        # and the containers leak exactly as they did before this module
        # existed. Degrading quiet is the contract; degrading SILENT is the
        # fail-open shape.
        (self.smm_dir / "system_context.json").write_text("not json")

        with patch("sys.stderr") as mock_stderr:
            # Returns rather than raising — a merge-gated removal must not
            # be blocked by an unreadable context.
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("system_context", written)

    def test_absent_declaration_reports_nothing(self):
        # The other half of the pair above, and the reason the corrupt case
        # cannot simply be folded into it: a project that declared no
        # teardown is the ordinary case for most projects, and must stay
        # silent. If both paths were silent the distinction would be
        # untestable; if both reported, every spawn would nag.
        with patch("sys.stderr") as mock_stderr:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        mock_stderr.write.assert_not_called()


class TestTeardownRelaysBothStreams(_TeardownTestCase):
    """A failing teardown used to report `stderr or stdout` — whichever
    stream carried the command's diagnosis, if it wasn't the one the
    `or` happened to pick, was silently dropped from the report."""

    def _run_and_get_output(self, command: str) -> str:
        """The RELAYED OUTPUT only, not the echoed command — the message
        prints the declared command verbatim first, and it happens to name
        both `echo` arguments too, so asserting against the whole message
        would pass even when the relay itself drops one of them."""
        self.declare_teardown(command)

        with patch("sys.stderr") as mock_stderr:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        return written.split(f"{command}\n", 1)[1]

    def test_stdout_diagnosis_survives_alongside_stderr_noise(self):
        output = self._run_and_get_output(
            "echo diagnosis-on-stdout; echo noise-on-stderr >&2; exit 1"
        )

        self.assertIn("diagnosis-on-stdout", output)
        self.assertIn("noise-on-stderr", output)

    def test_stderr_comes_first(self):
        output = self._run_and_get_output("echo on-stdout; echo on-stderr >&2; exit 1")

        self.assertLess(output.index("on-stderr"), output.index("on-stdout"))


class TestTeardownKillsProcessGroup(_TeardownTestCase):
    """AC4: a backgrounded, hanging child is killed as a group; run_teardown
    still returns rather than blocking on its pipe.

    The orphan is observed by PID, not by waiting for it to write a file.
    An earlier version of this test declared `(sleep 30 && echo > leaked.txt)`
    and asserted the file was absent — which the UNHARDENED implementation
    also satisfies, because it too returns at the 1s timeout, 29 seconds
    before the orphan would reveal itself. That test passed against the code
    it was meant to pin. Checking whether the process is still alive makes
    the difference observable at the moment we look.
    """

    def _declare_backgrounded_child(self) -> None:
        # Records the grandchild's pid, then blocks so the timeout fires
        # while it is still running.
        self.declare_teardown(
            "echo started > started.txt; "
            "{ sleep 30 & echo $! > child.pid; wait; } & wait"
        )

    def _child_pid(self) -> int:
        return int((self.wt_dir / "child.pid").read_text().strip())

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def test_backgrounded_hanging_child_is_killed_and_teardown_returns(self):
        self._declare_backgrounded_child()

        with (
            patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}),
            patch("sys.stderr"),
        ):
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        self.assertTrue((self.wt_dir / "started.txt").is_file())
        pid = self._child_pid()

        deadline = time.monotonic() + 2
        while self._alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertFalse(
            self._alive(pid),
            f"backgrounded grandchild (pid {pid}) survived the timeout — "
            "killing only the shell leaves it running, which is the orphan "
            "leak this hardening exists to prevent",
        )


class TestTeardownTimeoutReportsWhatTheChildSaid(_TeardownTestCase):
    """A bare "timed out after Ns" sends the operator back to reproduce the
    hang by hand. The output the command produced before it was killed is
    usually the only clue to why it hung, so the drain after the group kill
    has to reach the report."""

    def test_timeout_report_carries_the_childs_output(self):
        self.declare_teardown("echo stopping-db >&2; sleep 30")

        with (
            patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}),
            patch("sys.stderr") as mock_stderr,
        ):
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("timed out", written)
        self.assertIn("stopping-db", written)
        # Decoded, not a bytes repr — TimeoutExpired.stdout/.stderr are
        # bytes-typed even under text=True, which is why the runner re-raises
        # a str-carrying subclass instead of handing the original back.
        self.assertNotIn("b'", written)


class TestTeardownUnstartableCommand(_TeardownTestCase):
    """The likeliest real failure once story-002 wires the call site: the
    worktree path is already gone by the time teardown runs."""

    def test_missing_cwd_reports_and_returns(self):
        self.declare_teardown("echo never-runs > nope.txt")
        gone = self.wt_dir / "does-not-exist"

        with patch("sys.stderr") as mock_stderr:
            worktree_teardown.run_teardown(str(gone), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("failed to start", written)


class TestRunnerKillsGroupOnInterrupt(_TeardownTestCase):
    """An interrupt must not leave the declared command's tree running.

    `start_new_session=True` closes the timeout orphan door and opens another:
    it detaches the child from the controlling terminal, so a Ctrl-C no longer
    reaches it with the terminal's process group. If the runner caught only
    TimeoutExpired, KeyboardInterrupt would propagate past the one killpg that
    can still reach the group, leaving the whole tree running detached.
    """

    def test_keyboard_interrupt_still_kills_the_group(self):
        import _subprocess_env

        script = (
            "{ sleep 30 & echo $! > "
            + str(self.wt_dir / "child.pid")
            + "; wait; } & wait"
        )
        original = subprocess.Popen.communicate
        calls = {"n": 0}

        def side_effect(proc_self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # Let the child start and record its pid, then interrupt the
                # wait exactly as a Ctrl-C would. Later calls are the runner's
                # own bounded drain, which must still work.
                time.sleep(0.4)
                raise KeyboardInterrupt
            return original(proc_self, *args, **kwargs)

        with (
            patch.object(
                subprocess.Popen,
                "communicate",
                autospec=True,
                side_effect=side_effect,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            _subprocess_env.run_in_new_process_group(
                script,
                cwd=str(self.wt_dir),
                timeout=30,
                env=_subprocess_env.smm_child_env(self.smm_dir),
            )

        pid = int((self.wt_dir / "child.pid").read_text().strip())
        deadline = time.monotonic() + 2
        while TestTeardownKillsProcessGroup._alive(pid) and (
            time.monotonic() < deadline
        ):
            time.sleep(0.05)
        self.assertFalse(
            TestTeardownKillsProcessGroup._alive(pid),
            f"interrupted run left the detached grandchild (pid {pid}) alive",
        )


class TestTeardownTimeoutOverride(_TeardownTestCase):
    def test_the_default_leaves_room_for_the_removal_that_follows(self):
        """The bound is only a bound if it fires FIRST.

        Teardown reaches production inside `cleanup_teammate`, invoked from a
        close skill as an ordinary tool call with its own bound. When the two
        are equal, a hung teardown consumes the whole outer budget and the outer
        kill wins: the worktree is never removed, the branch never deleted, and
        the operator sees a timed-out call rather than this module's own
        report. Pinned as a MARGIN rather than a literal so tuning the number
        keeps the property.
        """
        callers_own_bound = 120  # the close skill's tool call takes the default
        self.assertLess(
            worktree_teardown._DEFAULT_TEARDOWN_TIMEOUT_S, callers_own_bound
        )

    def test_zero_falls_back_to_the_default(self):
        with patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "0"}):
            self.assertEqual(
                worktree_teardown._teardown_timeout(),
                worktree_teardown._DEFAULT_TEARDOWN_TIMEOUT_S,
            )

    def test_positive_override_is_honoured(self):
        with patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "42"}):
            self.assertEqual(worktree_teardown._teardown_timeout(), 42)


if __name__ == "__main__":
    unittest.main()
