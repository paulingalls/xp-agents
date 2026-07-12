#!/usr/bin/env python3
"""The suite must be INCAPABLE of launching a real `claude` agent.

A test in this suite once drove spawn_teammate.main() while stubbing only
create_worktree, relying on a not-yet-implemented refusal to stop main() before
it spawned. In the TDD red phase the refusal did not exist, so main() fell
through to run_with_tee and launched a REAL `claude -p`. That agent came up in
the repo with the plugin loaded, ran this suite as part of its lifecycle,
re-entered that test, and spawned another:

    pytest -> claude -p -> zsh -c pytest -> pytest -> claude -p -> ...

run_with_tee is a plain Popen with NO start_new_session, so the children are not
in a killable process group — they reparented to init and outlived the run. ~20
real, billable, recursive agents; one was alive for 22 minutes.

The lesson is not "remember to stub run_with_tee". It is that a test's safety
must never depend on the correctness of the code it is testing. conftest enforces
the prohibition at subprocess.Popen — the one syscall that can start a process —
so no test can reach the real binary however it is written. These tests pin that
backstop, and pin the one assumption it rests on.
"""

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import in_place_marker
import spawn_teammate
from conftest import CHILD_WAIT_TIMEOUT_S, RealAgentSpawnBlocked

_TESTS_DIR = Path(__file__).resolve().parent.parent


class TestTheIncidentIsNowAssertable(unittest.TestCase):
    """The incident itself, reproduced as a test that can NEVER cause it.

    Proving this guard works is delicate, because the obvious proof — disarm it
    and watch the suite spawn agents — IS the hazard. (It bit again during this
    very fix: a suite-wide run with the guard disarmed launched real agents, and
    when they were killed the run hung for 28 minutes on a subprocess that no
    longer existed.)

    So the negative case is asserted WITHOUT ever letting a spawn happen. Disarm
    the CLAIM — reproducing exactly what the TDD red phase looked like, where the
    refusal did not exist yet — and drive spawn_teammate.main() with run_with_tee
    UNSTUBBED. That is the precise shape that launched ~20 recursive agents. The
    guard converts it into a raise before Popen ever forks.

    No child process is created, nothing can hang, and this is safe to run in CI
    forever. "Would have spawned" is provable without spawning.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_main_that_fails_to_refuse_hits_the_guard_not_a_real_agent(self):
        """main() falling through to the spawn raises instead of forking."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name
        self.addCleanup(Path(prompt_path).unlink, True)

        with (
            # The red-phase state: the claim does not refuse anything.
            patch.object(
                in_place_marker, "claim_in_place_marker", lambda *a, **k: None
            ),
            patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
            # run_with_tee deliberately NOT stubbed — this is the unsafe shape.
            self.assertRaises(RealAgentSpawnBlocked),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "worktree-story-001",
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    prompt_path,
                    "--in-place",
                ]
            )


class TestRealAgentSpawnIsBlocked(unittest.TestCase):
    """The backstop itself."""

    def test_launching_the_real_agent_binary_raises(self):
        """The whole point: `claude` cannot be exec'd from a test."""
        with self.assertRaises(RealAgentSpawnBlocked):
            subprocess.Popen(["claude", "-p", "--name", "worktree-story-001"])

    def test_an_absolute_path_to_the_agent_is_also_blocked(self):
        """The guard matches on argv[0]'s BASENAME — resolving `claude` through
        PATH (or naming it absolutely) must not slip past it."""
        with self.assertRaises(RealAgentSpawnBlocked):
            subprocess.Popen(["/usr/local/bin/claude", "-p"])

    def test_ordinary_subprocesses_still_run(self):
        """The guard must be surgical: the suite spawns real python, git and bash
        children constantly (dead_pid/live_pid, the integration pipeline). Only
        the agent binary is off limits."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=CHILD_WAIT_TIMEOUT_S)
        self.assertEqual(proc.returncode, 0)

    def test_the_guard_survives_spawn_teammates_import_of_subprocess(self):
        """teammate_runner does `import subprocess` then `subprocess.Popen(...)`,
        so it resolves the name off the module object at CALL time and therefore
        sees the patched class. A `from subprocess import Popen` there would bind
        the original at import time and silently escape the guard."""
        sys.path.insert(0, str(_TESTS_DIR.parent / "scripts"))
        import teammate_runner

        self.assertIs(
            teammate_runner.subprocess.Popen,
            subprocess.Popen,
            "teammate_runner must resolve Popen off the subprocess module at call "
            "time, or the conftest backstop does not cover the real spawn path",
        )


class TestNoTestCanHangOnAChild(unittest.TestCase):
    """No test may block forever on a subprocess.

    A run once sat for 28 MINUTES with every xdist worker asleep and zero output,
    blocked on `proc.wait()` for a spawned agent that had been killed out from
    under it. A test that can hang with no output wedges CI and tells you nothing.

    So every wait on a child is bounded (conftest.reap / wait(timeout=...)). This
    pins that structurally — a bare `.wait()` cannot creep back in.
    """

    def _bare_waits(self, path: Path) -> list[str]:
        """AST, not grep: `.wait()` appears in prose all over this suite, and a
        text scan flags its own docstring. Only a real CALL counts."""
        tree = ast.parse(path.read_text(), filename=str(path))
        return [
            f"{path.relative_to(_TESTS_DIR)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("wait", "communicate", "join")
            and not any(kw.arg == "timeout" for kw in node.keywords)
            and not node.args  # wait(5) positional is bounded too
        ]

    def test_no_unbounded_wait_on_a_child_process(self):
        offenders = [
            hit for p in sorted(_TESTS_DIR.rglob("*.py")) for hit in self._bare_waits(p)
        ]
        self.assertEqual(
            offenders,
            [],
            "unbounded wait/communicate/join — pass timeout=, or use "
            "conftest.reap(). An unbounded wait can wedge CI for 28 minutes with "
            "no output, which has happened:\n  " + "\n  ".join(offenders),
        )


class TestEveryMainDriverLoadsTheGuard(unittest.TestCase):
    """The one assumption the backstop rests on.

    Under pytest, conftest is imported automatically for every test. Under
    `unittest discover` — which is what CI runs — it is imported only when a test
    module imports it. So a module that drives spawn_teammate.main() WITHOUT
    importing conftest would run with the guard absent, and the hazard would be
    back with no test failing.

    This pins that gap shut structurally, so it cannot be reopened silently.
    """

    def _test_modules(self) -> list[Path]:
        return [
            p
            for p in sorted(_TESTS_DIR.rglob("test_*.py"))
            if "spawn_teammate.main(" in p.read_text()
        ]

    def test_the_scan_actually_finds_the_main_drivers(self):
        """A guard test that silently matched nothing would pass forever."""
        self.assertGreaterEqual(
            len(self._test_modules()),
            5,
            "expected to find the spawn_teammate.main() drivers — if this scan "
            "matches nothing, the check below is vacuous",
        )

    def test_every_module_driving_main_imports_conftest(self):
        """...so the Popen backstop is loaded under `unittest discover` too."""
        for path in self._test_modules():
            tree = ast.parse(path.read_text(), filename=str(path))
            imports_conftest = any(
                (isinstance(n, ast.ImportFrom) and n.module == "conftest")
                or (
                    isinstance(n, ast.Import)
                    and any(a.name == "conftest" for a in n.names)
                )
                for n in ast.walk(tree)
            )
            self.assertTrue(
                imports_conftest,
                f"{path.relative_to(_TESTS_DIR)} drives spawn_teammate.main() but "
                "does not import conftest, so under `unittest discover` it runs "
                "WITHOUT the real-agent spawn backstop. Add an import from "
                "conftest.",
            )


if __name__ == "__main__":
    unittest.main()
