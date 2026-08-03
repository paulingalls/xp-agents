#!/usr/bin/env python3
"""Process hardening for verify_acceptance's declared-command call sites.

Both run paths shell out to whatever command the PROJECT declared, and both
were unsafe in their own way: `shell=True` with a timeout reaps only the
shell, so anything the command backgrounded outlives the run, and the
`--story` path carried no timeout at all, so a command that never returns
hung acceptance indefinitely. The fix is one shared runner
(`_subprocess_env.run_in_new_process_group`) at both sites.

Own file, not either path's suite: these pin ONE property — how a declared
command is executed and bounded — across BOTH paths, so splitting them by
path would put the two halves of a single contract in two places.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
from _bases import _HookTestCase
from conftest import make_sprint_dict, make_story_dict, verify_events

_VERIFY_ACCEPTANCE = (
    Path(__file__).parent.parent.parent / "scripts" / "verify_acceptance.py"
)


def _alive(pid: int) -> bool:
    """True while *pid* still names a live process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _HardeningTestCase(_HookTestCase):
    def _seed(self, ae: dict, story_id: str = "story-001") -> None:
        story = make_story_dict(id=story_id, acceptance_execution=ae)
        sprint = make_sprint_dict(sprint_id="sprint-012", stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _argv(self, *args: str) -> list[str]:
        return [
            sys.executable,
            str(_VERIFY_ACCEPTANCE),
            "--smm-dir",
            str(self.smm_dir),
            *args,
        ]

    def _run_from(
        self,
        cwd: Path,
        *args: str,
        extra_env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess:
        """Run the CLI with an EXPLICIT cwd and a bounded wall clock.

        `conftest.run_cli` inherits the runner's cwd — whatever directory the
        test session happened to start in — which cannot pin where a declared
        command's RELATIVE paths resolve. Its own bound is also too tight for
        a test that must let a hung command reach the runner's timeout first.
        """
        return subprocess.run(
            self._argv(*args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(extra_env or {})},
        )

    def _workdir(self) -> Path:
        """A throwaway cwd, distinct from smm_dir, to plant relative paths in."""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def _verify_events(self) -> list[dict]:
        return verify_events(self._read_events())


class TestTimeoutKillsProcessGroup(_HardeningTestCase):
    """AC1: a declared command that BACKGROUNDS a child and then hangs must
    lose the whole tree at the timeout, not just the shell.

    `subprocess.run(shell=True, timeout=...)` kills only the shell it spawned;
    anything the command backgrounded — a dev server, a database, a stack —
    keeps running long after the run has moved on. Running the command in its
    own session lets the timeout `killpg` the group instead.

    The orphan is observed BY PID, polled at the moment we look. story-001
    shipped two process-group tests that asserted on an artifact the orphan
    writes ~29s later, and passed against completely unhardened code, because
    the unhardened path also returns at the timeout — 29 seconds before the
    orphan would have revealed itself. Checking liveness makes the difference
    observable now. Template: test_worktree_teardown.TestTeardownKillsProcessGroup.
    """

    def _seed_backgrounding_command(self) -> Path:
        pidfile = self.smm_dir / "orphan.pid"
        # The grandchild's fds go to /dev/null so it never holds the parent's
        # pipes: whether it SURVIVES is then the only thing measured here, not
        # whether the parent blocks draining it.
        self._seed(
            {
                "type": "bash",
                "commands": [f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"],
            }
        )
        return pidfile

    def _assert_reaped(self, pidfile: Path) -> None:
        pid = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 2
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(
            _alive(pid),
            f"backgrounded child (pid {pid}) survived the timeout — killing "
            "only the shell orphans everything the acceptance command started",
        )

    def test_batch_path_reaps_the_backgrounded_child(self):
        pidfile = self._seed_backgrounding_command()
        result = self._run_from(
            self._workdir(), "--sprint", extra_env={"VERIFY_CMD_TIMEOUT_S": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self._assert_reaped(pidfile)


class TestDeclaredCommandCwd(_HardeningTestCase):
    """AC5: a declared command's relative paths resolve against the cwd the
    runner was invoked from — unchanged by the hardening.

    The hardened runner takes cwd as a REQUIRED positional, and `smm_dir` is
    the nearest Path in scope at both call sites. Passing it would silently
    relocate every declared command, breaking every relative path in a way
    that reads as a missing-test error rather than a cwd bug. These fail
    loudly instead.
    """

    def test_batch_path_resolves_against_the_invocation_cwd(self):
        workdir = self._workdir()
        (workdir / "marker.txt").write_text("here")
        self._seed({"type": "bash", "commands": ["test -f marker.txt"]})

        result = self._run_from(workdir, "--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = self._verify_events()[0]["metadata"]
        self.assertEqual(
            meta["verify_status"],
            "green",
            "a relative-path AC command did not resolve against the "
            f"invocation cwd; failing={meta.get('failing')!r}",
        )


if __name__ == "__main__":
    unittest.main()
