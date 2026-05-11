#!/usr/bin/env python3
"""Tests for the liveness watchdog in spawn_teammate.py.

Covers _ActivityWatchdog (unit) and its integration with run_with_tee.

Why a separate file: spawn_teammate.py's primary test file
(test_spawn_teammate.py) had grown past the project's 500-line
budget. The watchdog tests are a cohesive subset that splits cleanly
along feature lines.
"""

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
        import spawn_teammate

        return spawn_teammate._ActivityWatchdog(
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

        import spawn_teammate

        # rc=-15 = SIGTERM signal exit; checked after the loop unblocks.
        # block_after=1.0 outlasts the patched watchdog window
        # (timeout 0.3 + kill_grace 0.2 = ~0.5s) with 2x safety margin
        # while keeping wall-clock cost low — the for-loop is parked
        # inside the iterator's time.sleep(block_after) and only
        # unblocks when that sleep returns (terminate() is a MagicMock
        # no-op against the iterator).
        proc = self._fake_popen(["hello\n"], returncode=-15, block_after=1.0)
        with (
            patch("spawn_teammate.subprocess.Popen", return_value=proc),
            patch.object(spawn_teammate, "_WATCHDOG_TIMEOUT_S", 0.3),
            patch.object(spawn_teammate, "_WATCHDOG_POLL_INTERVAL_S", 0.05),
            patch.object(spawn_teammate, "_WATCHDOG_KILL_GRACE_S", 0.2),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            spawn_teammate.run_with_tee(
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

        import spawn_teammate

        proc = self._fake_popen(["a\n", "b\n", "c\n"])
        with (
            patch("spawn_teammate.subprocess.Popen", return_value=proc),
            patch.object(spawn_teammate, "_WATCHDOG_TIMEOUT_S", 0.5),
            patch.object(spawn_teammate, "_WATCHDOG_POLL_INTERVAL_S", 0.05),
        ):
            spawn_teammate.run_with_tee(
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


if __name__ == "__main__":
    unittest.main()
