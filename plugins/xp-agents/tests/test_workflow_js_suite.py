#!/usr/bin/env python3
"""Run the JavaScript workflow suite from inside the Python one.

WHY FROM HERE rather than its own lefthook entry. Everything that must run the
JS already runs pytest: CI, the pre-push gate, and any developer typing
`pytest -n auto`. Driving it from here means the JS cannot be green in one place
and unrun in another, and a missing `node` fails a test instead of silently
skipping a surface no other gate covers. The repo already shells a runner out of
its own suite — the dual-packaging probes invoke `python -m pytest` the same way.

THE FLOOR IS THE POINT, and it is not defensive programming. Measured on Node
22.15 while wiring this up:

    node --test '<glob matching nothing>'   ->  # tests 0, exit 0

A gate wired on the exit code alone therefore passes forever the moment the glob
stops matching — a rename, a moved directory, a changed suffix. That is the
silent-pass shape `_SHELL_FLOOR` and the prose-group floors exist to refuse, and
a `.js` surface is where it would go unnoticed longest, since no size, lint,
format or type gate in this repo discovers one.

Also measured: `node --test <dir>` FAILS on this version (it tries to load the
directory as a module), so the invocation is a glob and the glob is what the
floor protects.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_TESTS_ROOT = Path(__file__).parent
_JS_GLOB = str(_TESTS_ROOT / "workflows" / "*_test.js")

# Every `test(...)` in tests/workflows/. Raise it when a suite lands, the way the
# band ceilings move: the number is a measurement, and lowering it silently is
# how a floor stops holding anything.
_MIN_PASSING = 16


def _run_node_test() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "--test", _JS_GLOB],
        capture_output=True,
        text=True,
        cwd=_TESTS_ROOT.parent.parent.parent,
    )


def _passing_count(stdout: str) -> int:
    """The `# pass N` line of TAP output, or -1 when it is absent."""
    for line in stdout.splitlines():
        if line.startswith("# pass "):
            return int(line.removeprefix("# pass ").strip())
    return -1


class TestTheWorkflowJsSuiteRuns(unittest.TestCase):
    """The JS half of the broad-review workflow, gated where everything runs."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            # Deliberately NOT a skip. The workflow script has no other gate —
            # no linter, no formatter, no type-checker, no size pin discovers a
            # `.js` — so skipping here would leave it wholly unchecked on the
            # machine doing the pushing. `make setup` names the fix.
            raise AssertionError(
                "node is not on PATH, so the workflow suite cannot run and the "
                "shipped workflow script would be committed unchecked. Install "
                "Node (>=20) and re-run `make setup`."
            )
        cls.result = _run_node_test()

    def test_the_js_suite_passes(self):
        self.assertEqual(
            self.result.returncode,
            0,
            f"node --test failed:\n{self.result.stdout}\n{self.result.stderr}",
        )

    def test_it_actually_ran_something(self):
        """The non-vacuity floor — see the module docstring for the measurement.

        Without this, a glob that stops matching turns the whole JS gate into a
        no-op that reports success, and the exit-code assertion above would
        agree with it.
        """
        passing = _passing_count(self.result.stdout)
        self.assertGreaterEqual(
            passing,
            _MIN_PASSING,
            f"expected at least {_MIN_PASSING} passing JS tests, saw {passing}. "
            f"Zero means the glob {_JS_GLOB!r} matched nothing — which node "
            f"reports as success.\n{self.result.stdout}",
        )


if __name__ == "__main__":
    unittest.main()
