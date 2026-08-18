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
import unittest
from pathlib import Path

_TESTS_ROOT = Path(__file__).parent
_REPO_ROOT = _TESTS_ROOT.parent.parent.parent
_JS_GLOB = str(_TESTS_ROOT / "workflows" / "*_test.js")

# Every `test(...)` in tests/workflows/. Raise it when a suite lands, the way the
# band ceilings move: the number is a measurement, and lowering it silently is
# how a floor stops holding anything.
_MIN_PASSING = 40


def _run_node_test() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "--test", _JS_GLOB],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
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


class TestNodeIsProvisionedWhereThisRuns(unittest.TestCase):
    """The class above turns a missing node into a FAILURE, which is only the
    right call if the places that run this suite actually provide one.

    Two of them are not the developer's machine, and neither would say anything
    useful when it broke: CI would fail this module with "node is not on PATH"
    on a change touching no JavaScript, and a fresh clone would hit the same at
    its first push. So each has a provisioning step, and each step is pinned
    here rather than trusted — an unpinned `setup-node` is one dependency-bump
    PR away from being dropped as unused.
    """

    def test_ci_provisions_node(self):
        workflow = (_REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
        self.assertIn(
            "actions/setup-node",
            workflow,
            "CI runs this module and it fails rather than skips without node, "
            "so the workflow must provision one — relying on whatever the "
            "runner image happens to ship makes the coverage image-dependent",
        )

    def test_make_setup_probes_for_node(self):
        makefile = (_REPO_ROOT / "Makefile").read_text()
        self.assertIn(
            "node --test",
            makefile,
            "`make setup` must probe `node --test`, matching how it probes "
            "pytest: the capability, at the moment a clone is being wired up, "
            "rather than a red push later on a change that touched no JS",
        )

    def test_the_node_probe_does_not_cost_a_clone_its_gates(self):
        """Ordering, and it is the whole difference between a warning and an
        outage.

        The probe first sat beside the pytest one, where it exits 1 BEFORE
        `lefthook install`. A box with pytest and lefthook but no Node then came
        away with no gates at all — ungated commits and pushes, silently, which
        is the exact state CLAUDE.md warns a clone that skips `make setup` ends
        up in. Before the probe existed that same box got every gate and merely
        lacked the JS suite, so the check for a missing capability cost the
        capabilities that were present.

        Asserted on position rather than on the message: a probe that runs after
        the install can still fail loudly, and should.
        """
        makefile = (_REPO_ROOT / "Makefile").read_text()
        install_at = makefile.index("lefthook install")
        probe_at = makefile.index("node --test --help")
        self.assertLess(
            install_at,
            probe_at,
            "the node probe must run AFTER `lefthook install` — exiting before "
            "it leaves the clone with no commit or push gate at all",
        )


if __name__ == "__main__":
    unittest.main()
