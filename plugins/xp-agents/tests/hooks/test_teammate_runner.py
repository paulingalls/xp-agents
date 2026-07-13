#!/usr/bin/env python3
"""Tests for teammate_runner.py — subprocess tee + liveness watchdog.

Covers _ActivityWatchdog (unit), its integration with run_with_tee, and
run_with_tee's resilience to a downstream stdout consumer (the output
filter) closing mid-stream. Lives beside the runner code it exercises.

The module's OTHER half — the /tmp prompt/log namespace (_project_dir,
_path_token) — is tested in test_teammate_runner_paths.py: a pure
path-resolution concern, no subprocess involved, and splitting it keeps both
files under the size cap.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestActivityWatchdog(unittest.TestCase):
    """_ActivityWatchdog terminates a subprocess that goes silent.

    Why this exists: a spawned `claude -p` can block indefinitely inside
    an HTTPS POST to the model API (observed in concern e1a8f7e17d84
    where a teammate produced zero output for 31 minutes overnight).
    The watchdog runs in a thread alongside the run_with_tee main loop,
    which calls .ping() on each line read; if pings stop for longer
    than the timeout, the watchdog terminates the subprocess so the
    main loop sees stdout EOF and the existing CalledProcessError
    recovery path takes over.

    Tests use a tiny FakeProc with terminate/kill/wait counters rather
    than MagicMock — the assertions are about which methods were called
    and in what order, which is easier to verify with explicit fields.
    """

    class _FakeProc:
        """Minimal stand-in for subprocess.Popen."""

        def __init__(
            self,
            *,
            terminate_raises: bool = False,
            wait_raises_timeout: bool = False,
        ):
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0
            self._terminate_raises = terminate_raises
            self._wait_raises_timeout = wait_raises_timeout

        def terminate(self) -> None:
            self.terminate_calls += 1
            if self._terminate_raises:
                raise OSError("simulated terminate failure")

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self._wait_raises_timeout:
                raise subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout or 0)
            return 0

        def kill(self) -> None:
            self.kill_calls += 1

    def _make_watchdog(self, proc, timeout_s: float = 1.0):
        import teammate_runner

        return teammate_runner._ActivityWatchdog(
            proc, name="test", timeout_s=timeout_s, poll_interval_s=0.05
        )

    def test_terminates_after_timeout_with_no_ping(self):
        """No pings → watchdog calls proc.terminate() once after timeout
        elapses. This is the core failure-detection path."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)

    def test_does_not_terminate_when_pinged_within_timeout(self):
        """Steady pings keep the watchdog quiet — covers the legitimate
        long-thinking case where the spawned subprocess is producing
        stream-event lines and the main loop pings on each one."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        for _ in range(8):
            _t.sleep(0.1)
            wd.ping()
        wd.stop()
        self.assertEqual(proc.terminate_calls, 0)

    def test_stop_prevents_termination(self):
        """Calling .stop() before the timeout fires — the normal
        completion path — must not call terminate()."""
        import time as _t

        proc = self._FakeProc()
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        wd.stop()
        _t.sleep(0.6)
        self.assertEqual(proc.terminate_calls, 0)
        self.assertEqual(proc.kill_calls, 0)

    def test_terminate_failure_does_not_propagate(self):
        """If proc.terminate() raises (e.g. process already exited), the
        watchdog thread must not crash — it has no exception channel
        back to the parent and a crash would leak the silence
        condition."""
        import time as _t

        proc = self._FakeProc(terminate_raises=True)
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)

    def test_escalates_to_kill_when_terminate_does_not_exit(self):
        """SIGTERM may be ignored when the child is blocked in a C-level
        recv() (the suspected hang mode). After a 10s grace, the
        watchdog must escalate to SIGKILL or the recovery never fires."""
        import time as _t

        proc = self._FakeProc(wait_raises_timeout=True)
        wd = self._make_watchdog(proc, timeout_s=0.3)
        wd.start()
        _t.sleep(0.6)
        wd.stop()
        self.assertEqual(proc.terminate_calls, 1)
        self.assertEqual(proc.kill_calls, 1)


class TestRunWithTeeWatchdog(unittest.TestCase):
    """run_with_tee starts the watchdog, pings it on each line read,
    and stops it on completion. Verifies wiring, not the watchdog
    itself (covered by TestActivityWatchdog).
    """

    def setUp(self):
        import tempfile

        self.log_dir = Path(tempfile.mkdtemp())

    def _blocking_iter(self, lines: list[str], block_after: float = 30.0):
        """Iterator that yields *lines* then blocks for *block_after*
        seconds before raising StopIteration.

        Simulates a hung subprocess: produces some output, then goes
        silent. The block must outlast the test's watchdog timeout —
        otherwise the iterator returns naturally and we're testing the
        clean-exit path, not the watchdog kill path.
        """
        import time as _t

        yield from lines
        _t.sleep(block_after)

    def _fake_popen(
        self,
        lines: list[str],
        *,
        returncode: int = 0,
        block_after: float | None = None,
    ):
        """MagicMock subprocess. When *block_after* is set, stdout
        iterator blocks for that many seconds after yielding *lines*
        — simulates a hung subprocess. Otherwise yields *lines* and
        exits cleanly.
        """
        from unittest.mock import MagicMock

        fake = MagicMock()
        if block_after is None:
            fake.stdout = iter(lines)
        else:
            fake.stdout = self._blocking_iter(lines, block_after=block_after)
        fake.returncode = returncode
        return fake

    def test_terminates_subprocess_after_silence(self):
        """run_with_tee starts the watchdog with the production timeout
        constants; when the subprocess produces output and then blocks,
        the watchdog terminates it and run_with_tee surfaces the
        non-zero exit as CalledProcessError. The integration point is:
        ping → reset silence timer → eventual kill when pings stop."""
        from unittest.mock import patch

        import teammate_runner

        # rc=-15 = SIGTERM signal exit; checked after the loop unblocks.
        # block_after=1.0 outlasts the patched watchdog window
        # (timeout 0.3 + kill_grace 0.2 = ~0.5s) with 2x safety margin
        # while keeping wall-clock cost low — the for-loop is parked
        # inside the iterator's time.sleep(block_after) and only
        # unblocks when that sleep returns (terminate() is a MagicMock
        # no-op against the iterator).
        proc = self._fake_popen(["hello\n"], returncode=-15, block_after=1.0)
        with (
            patch("teammate_runner.subprocess.Popen", return_value=proc),
            patch.object(teammate_runner, "_WATCHDOG_TIMEOUT_S", 0.3),
            patch.object(teammate_runner, "_WATCHDOG_POLL_INTERVAL_S", 0.05),
            patch.object(teammate_runner, "_WATCHDOG_KILL_GRACE_S", 0.2),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            teammate_runner.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-hung",
                log_dir=self.log_dir,
            )
        self.assertGreaterEqual(
            proc.terminate.call_count,
            1,
            "watchdog must have called terminate() on the silent subprocess",
        )
        log = (self.log_dir / "teammate-hung.log").read_text()
        self.assertIn("hello", log)

    def test_does_not_terminate_when_subprocess_streams(self):
        """A subprocess that emits all lines and exits cleanly within
        the watchdog window must NOT be terminated — pings reset the
        silence timer on every line read."""
        from unittest.mock import patch

        import teammate_runner

        proc = self._fake_popen(["a\n", "b\n", "c\n"])
        with (
            patch("teammate_runner.subprocess.Popen", return_value=proc),
            patch.object(teammate_runner, "_WATCHDOG_TIMEOUT_S", 0.5),
            patch.object(teammate_runner, "_WATCHDOG_POLL_INTERVAL_S", 0.05),
        ):
            teammate_runner.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-clean",
                log_dir=self.log_dir,
            )
        self.assertEqual(
            proc.terminate.call_count,
            0,
            "watchdog must not fire when subprocess completes within timeout",
        )


class TestRunWithTeeBrokenStdout(unittest.TestCase):
    """A downstream stdout consumer (the output filter) dying mid-stream must
    NOT kill the teammate. run_with_tee stops writing to stdout on BrokenPipe,
    keeps draining proc.stdout to the log so the teammate never blocks on a
    full pipe, and reports stdout_broken=True so the caller can skip the rc=0
    promote (the filter that owns report/coordination-clear never finished).
    """

    def setUp(self):
        import tempfile

        self.log_dir = Path(tempfile.mkdtemp())

    def test_broken_stdout_keeps_logging_drains_and_flags(self):
        from unittest.mock import MagicMock, patch

        import teammate_runner

        proc = MagicMock()
        proc.stdout = iter(["a\n", "b\n", "c\n"])
        proc.returncode = 0

        class _BrokenStdout:
            """Succeeds on the first write, then raises BrokenPipeError."""

            def __init__(self):
                self.writes = 0

            def write(self, s):
                self.writes += 1
                if self.writes >= 2:
                    raise BrokenPipeError("downstream closed")

            def flush(self):
                pass

        with (
            patch("teammate_runner.subprocess.Popen", return_value=proc),
            patch.object(teammate_runner.sys, "stdout", _BrokenStdout()),
        ):
            broken = teammate_runner.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-brk",
                log_dir=self.log_dir,
            )

        self.assertTrue(broken, "run_with_tee must report stdout_broken=True")
        log = (self.log_dir / "teammate-brk.log").read_text()
        for ch in ("a", "b", "c"):
            self.assertIn(
                ch, log, "every line must still reach the log after stdout breaks"
            )
        proc.wait.assert_called()

    def test_intact_stdout_reports_not_broken(self):
        """The happy path returns stdout_broken=False so the caller promotes."""
        from unittest.mock import MagicMock, patch

        import teammate_runner

        proc = MagicMock()
        proc.stdout = iter(["x\n", "y\n"])
        proc.returncode = 0

        with patch("teammate_runner.subprocess.Popen", return_value=proc):
            broken = teammate_runner.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-ok",
                log_dir=self.log_dir,
            )

        self.assertFalse(broken)

    def test_log_write_failure_keeps_draining_not_raise(self):
        """A mid-stream log write OSError (e.g. full disk) must not propagate:
        the tee is best-effort, and stopping the drain would deadlock a healthy
        child on a full stdout pipe. run_with_tee drops the tee and drains on."""
        from unittest.mock import MagicMock, patch

        import teammate_runner

        proc = MagicMock()
        proc.stdout = iter(["a\n", "b\n", "c\n"])
        proc.returncode = 0

        class _FailingLog:
            """Accepts the session header, then raises OSError on every line."""

            def __init__(self):
                self.header_seen = False

            def write(self, s):
                if not self.header_seen:
                    self.header_seen = True
                    return
                raise OSError("disk full")

            def flush(self):
                pass

            def close(self):
                pass

        with (
            patch("teammate_runner.subprocess.Popen", return_value=proc),
            patch.object(Path, "open", return_value=_FailingLog()),
        ):
            broken = teammate_runner.run_with_tee(
                ["fake"],
                cwd=".",
                env={},
                stdin=None,
                name="teammate-logfail",
                log_dir=self.log_dir,
            )

        # Drained to completion without raising; stdout intact → not broken.
        self.assertFalse(broken)
        proc.wait.assert_called()


class TestRunWithTeeOnSpawn(unittest.TestCase):
    """on_spawn hands out the REAL child's pid, against a REAL subprocess.

    This is the load-bearing line of the in-place marker fix: the marker must
    record the pid of the claude CHILD, not of this supervising process, because
    the child is a plain Popen with no start_new_session and can outlive a signal
    delivered here. Every other test of that fix stubs run_with_tee and calls
    on_spawn itself — which proves only that the caller folds a pid it was handed,
    not that the runner ever hands one out. Delete the on_spawn call and those
    stay green; these do not.
    """

    def setUp(self):
        import tempfile

        self.log_dir = Path(tempfile.mkdtemp())

    def test_on_spawn_receives_the_real_child_pid(self):
        import teammate_runner

        seen: list[int] = []

        teammate_runner.run_with_tee(
            cmd=[sys.executable, "-c", "print('hi')"],
            cwd=".",
            env=dict(os.environ),
            stdin=None,
            name="teammate-onspawn",
            log_dir=self.log_dir,
            on_spawn=seen.append,
        )

        self.assertEqual(len(seen), 1, "on_spawn must fire exactly once")
        child = seen[0]
        self.assertGreater(child, 0)
        self.assertNotEqual(
            child,
            os.getpid(),
            "on_spawn handed out OUR pid, not the child's — recording it would "
            "let a reap delete a live teammate's marker once we are killed",
        )
        # It named a real process: reaped by proc.wait(), so it is now gone.
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_a_failing_on_spawn_kills_the_child_and_raises(self):
        """If the child's pid cannot be recorded, nothing can later prove the
        child alive — so a reap would delete a LIVE teammate's marker. Kill the
        child rather than leave it running unrecorded.

        Note the finally in run_with_tee does NOT kill: it stops the watchdog and
        then proc.wait()s. Simply letting the exception fly past it would deadlock
        on a child whose stdout nobody is reading.
        """
        from unittest.mock import patch

        import teammate_runner

        seen: list[int] = []
        spawned: list[subprocess.Popen] = []
        real_popen = subprocess.Popen

        def capture(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            spawned.append(proc)
            return proc

        def boom(pid: int) -> None:
            seen.append(pid)
            raise OSError("cannot write marker")

        with (
            patch.object(teammate_runner.subprocess, "Popen", capture),
            self.assertRaises(OSError),
        ):
            teammate_runner.run_with_tee(
                # Long-lived and SILENT: it would outlive us if not killed.
                cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=".",
                env=dict(os.environ),
                stdin=None,
                name="teammate-onspawn-fail",
                log_dir=self.log_dir,
                on_spawn=boom,
            )

        self.assertEqual(len(seen), 1)
        # Assert on the Popen object, NOT os.kill(pid, 0): once the child is
        # reaped its pid is free for reuse, and under `pytest -n auto` a sibling
        # worker's subprocess really does recycle it — the probe then finds a
        # LIVE unrelated process and the test flakes. (The same pid-reuse hazard
        # this sprint's reap exists to bound.) returncode is set only by wait(),
        # so a non-None value proves killed-and-reaped, immune to reuse.
        proc = spawned[0]
        self.assertIsNotNone(
            proc.returncode,
            "child was left running unreaped after on_spawn failed",
        )
        self.assertNotEqual(proc.returncode, 0, "child should have been killed")


if __name__ == "__main__":
    unittest.main()
