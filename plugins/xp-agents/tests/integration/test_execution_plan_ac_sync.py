#!/usr/bin/env python3
"""Pin: every delivered milestone's acceptance_execution commands point at
real, pytest-collectable test files.

Story-014 motivation: M-2 of the active execution_plan.json referenced
plugins/xp-agents/tests/hooks/test_stop_close_marker.py — a file that
never existed. pytest exits 0 with "no tests ran" when given a path
inside a collection root that doesn't resolve, so the AC gate silently
passed even though M-2 was never actually verified by the listed tests.

This pin walks the live execution_plan.json (resolved via
_common.resolve_smm_dir()) and, for every milestone whose status is
"delivered", runs `pytest --collect-only -q <command-args>`. The pin
fails if pytest collects zero tests for any AC command. Planned
milestones are skipped — they ship before they're verified.
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
        smm_dir = _common.resolve_smm_dir()
        if smm_dir is None or not (smm_dir / "execution_plan.json").exists():
            raise unittest.SkipTest(
                "No execution_plan.json in resolved SMM dir — pin skipped"
            )
        cls.plan = load_plan(smm_dir)
        if cls.plan is None:
            raise unittest.SkipTest("load_plan returned None")

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
            out.append(tok)
        return out

    def test_delivered_milestone_ac_points_at_collectable_tests(self):
        for m in self.plan.get("milestones", []):
            if m.get("status") != "delivered":
                continue
            label = f"M-{m.get('number')} {m.get('name')}"
            ac = m.get("acceptance_execution")
            if not ac:
                continue
            for cmd in extract_commands(ac):
                with self.subTest(milestone=label, command=cmd):
                    args = self._pytest_args_from(cmd)
                    self.assertTrue(
                        args,
                        f"{label}: empty pytest args from {cmd!r}",
                    )
                    result = subprocess.run(
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
                    # pytest exit codes:
                    #   0 = tests collected
                    #   4 = usage error (e.g., missing path)
                    #   5 = no tests collected
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
