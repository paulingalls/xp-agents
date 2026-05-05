#!/usr/bin/env python3
"""Pin: every delivered milestone's acceptance_execution commands point at
real, pytest-collectable test files.

Story-014 motivation: M-2 of the active execution_plan.json referenced
plugins/xp-agents/tests/hooks/test_stop_close_marker.py — a file that
never existed. pytest exits 0 with "no tests ran" when given a path
inside a collection root that doesn't resolve, so the AC gate silently
passed even though M-2 was never actually verified by the listed tests.

Two test methods:

- ``test_fixture_milestone_ac_points_at_collectable_tests`` walks an
  in-memory synthesized plan and ALWAYS runs (no SMM dependency). One
  fixture milestone references this very file (must collect); a second
  references a deliberately missing path (must NOT collect — proves the
  pin's `returncode == 0` check would catch the M-2-style regression).
  This is the story-015 fix: a fresh clone / CI runner with no live SMM
  can no longer silently report `OK(skipped=1)`.

- ``test_live_milestone_ac_points_at_collectable_tests`` walks the live
  ``execution_plan.json`` (resolved via ``_common.resolve_smm_dir()``)
  and skips when no live SMM is resolvable. When live SMM IS available,
  it runs in addition to the fixture method.
"""

import shlex
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from _acceptance_execution import extract_commands
from conftest import _PLUGIN_ROOT
from execution_plan_store import load_plan

_REPO_ROOT = _PLUGIN_ROOT.parent.parent

# Fixture path constants — kept at module scope so the docstring of the
# fixture test stays grounded in the same identifiers the assertions use.
# `_FIXTURE_MISSING_PATH` MUST stay non-existent: the regression-vector
# sub-assertion asserts pytest fails to collect it. If a future
# contributor creates a file at this path the assertion silently flips to
# the wrong direction and the M-2 vector is no longer verified.
_FIXTURE_REAL_PATH = (
    "plugins/xp-agents/tests/integration/test_execution_plan_ac_sync.py"
)
_FIXTURE_MISSING_PATH = (
    "plugins/xp-agents/tests/integration/test_does_not_exist_story_015.py"
)


class TestExecutionPlanACSync(unittest.TestCase):
    """Every delivered milestone's AC must point at collectable tests."""

    @classmethod
    def setUpClass(cls):
        # The pin shells `sys.executable -m pytest --collect-only`. If the
        # active interpreter has no pytest installed (e.g., running via
        # `python3 -m unittest discover` on a system Python), every subTest
        # would fail with a misleading "No module named pytest". Skip cleanly
        # instead — this test is inherently pytest-only.
        probe = subprocess.run(
            [sys.executable, "-c", "import pytest"],
            capture_output=True,
        )
        if probe.returncode != 0:
            raise unittest.SkipTest(
                f"pytest not importable under {sys.executable} — pin requires pytest"
            )

    def _pytest_args_from(self, command: str) -> list[str]:
        """Return args after the leading 'pytest' token, with -n auto stripped.

        --collect-only runs in-process; pytest-xdist isn't required (and may
        not be on PATH in every contributor's environment). Stripping -n
        keeps the pin runnable without xdist installed.
        """
        tokens = shlex.split(command)
        if tokens and tokens[0] == "pytest":
            tokens = tokens[1:]
        out: list[str] = []
        skip_next = False
        for tok in tokens:
            if skip_next:
                skip_next = False
                continue
            if tok == "-n":
                skip_next = True
                continue
            if tok.startswith("-n") and len(tok) > 2:
                # `-nauto` / `-n4` no-space form (pytest-xdist accepts both)
                continue
            out.append(tok)
        return out

    def _collect(self, command: str) -> subprocess.CompletedProcess:
        """Run `pytest --collect-only` for `command`, return the result.

        Raises AssertionError if the command yields no pytest args (caller
        relies on a non-empty argv to avoid pytest defaulting to `.`, which
        would mask a fully-malformed AC entry).
        """
        args = self._pytest_args_from(command)
        self.assertTrue(args, f"empty pytest args from {command!r}")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                *args,
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_fixture_milestone_ac_points_at_collectable_tests(self):
        """In-memory fixture pin: ALWAYS runs, no SMM dependency.

        Two sub-assertions stand in for a synthesized plan with two
        delivered milestones — one AC points at this very file (must
        collect, returncode == 0); the other points at a deliberately
        missing path (must NOT collect, returncode != 0). The second
        sub-assertion proves the pin's equality check is the live
        regression vector for the M-2 story-014 bug, so a fresh-clone
        CI cannot silently skip the verification.
        """
        real_cmd = f"pytest {_FIXTURE_REAL_PATH}"
        real_result = self._collect(real_cmd)
        self.assertEqual(
            real_result.returncode,
            0,
            f"Fixture real-path AC failed to collect: {real_cmd!r}\n"
            f"  exit={real_result.returncode}\n"
            f"  stdout={real_result.stdout}\n"
            f"  stderr={real_result.stderr}",
        )

        missing_cmd = f"pytest {_FIXTURE_MISSING_PATH}"
        missing_result = self._collect(missing_cmd)
        self.assertNotEqual(
            missing_result.returncode,
            0,
            f"Pin's regression-vector check is broken: pytest collected the "
            f"deliberately missing path {_FIXTURE_MISSING_PATH!r} (exit 0).\n"
            f"  stdout={missing_result.stdout}\n"
            f"  stderr={missing_result.stderr}",
        )

    def test_live_milestone_ac_points_at_collectable_tests(self):
        """Live pin: walk the resolved execution_plan.json. Skips when no
        live SMM is available (e.g., fresh clone, CI runner). The fixture
        test above is the always-on guarantee.

        pytest exit codes:
          0 = tests collected
          4 = usage error (e.g., missing path)
          5 = no tests collected
        """
        smm_dir = _common.resolve_smm_dir()
        if smm_dir is None or not (smm_dir / "execution_plan.json").exists():
            self.skipTest("No execution_plan.json in resolved SMM dir")
        plan = load_plan(smm_dir)
        if plan is None:
            self.skipTest("load_plan returned None")
        for m in plan.get("milestones", []):
            if m.get("status") != "delivered":
                continue
            label = f"M-{m.get('number')} {m.get('name')}"
            ac = m.get("acceptance_execution")
            if not ac:
                continue
            for cmd in extract_commands(ac):
                with self.subTest(milestone=label, command=cmd):
                    result = self._collect(cmd)
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"{label}: pytest collect failed for {cmd!r}\n"
                        f"  exit={result.returncode}\n"
                        f"  stdout={result.stdout}\n"
                        f"  stderr={result.stderr}",
                    )


if __name__ == "__main__":
    unittest.main()
