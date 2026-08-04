#!/usr/bin/env python3
"""Free-close gate: narrowing, aggregation prose, and the collapse rule.

Free close has NO story, so 016's story-id entry point could never serve it —
the branch diff is its only possible input. story-017 made that the input for
both close modes, which also closes the drift hole on the story path.

The collapse rule is why this file exists separately from the story-close gate
suite: a broad free branch can touch every declared surface, and running N
narrowed commands then costs MORE than the one full command they replaced.
Collapse is expressed as "no narrowing available" — the door returns empty and
the existing fallback runs the full suite once.

THE DEAD-TEST TRAP: this repo declares no surface `paths`, so every assertion
here runs against an empty selection unless the fixture seeds one.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT

_SURFACE_MODULE = _PLUGIN_ROOT / "skills" / "_preload_surface.sh"
_FREE_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"
)
_FREE_CLOSE_SKILL = _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md"

_FULL = "pytest -n auto THE-WHOLE-SUITE"


def _surface(name: str, **overrides: object) -> dict:
    base: dict = {"name": name, "signals": ["detected"], "status": "covered"}
    base.update(overrides)
    return base


class _FreeCloseResolution(unittest.TestCase):
    def _seed(self, surfaces: list[dict]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        smm = tmp / "data" / "proj" / "smm"
        smm.mkdir(parents=True)
        (smm / "events.jsonl").write_text("")
        (smm / "system_context.json").write_text(
            json.dumps(
                {
                    "product": "x",
                    "architecture_overview": "x",
                    "stack": {"languages": ["Python"], "test_command": _FULL},
                    "modules": [],
                    "conventions": [],
                    "principles": [],
                    "project_specific": [],
                    "acceptance_surfaces": surfaces,
                }
            )
        )
        return smm

    def _resolve(self, smm: Path, paths: str) -> str:
        script = (
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; SMM_DIR="{smm}"; '
            f'source "{_SURFACE_MODULE}"; '
            f'emit_gate_commands "{paths}" "{_FULL}"'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "SMM_DIR": str(smm)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @staticmethod
    def _commands(stdout: str) -> list[str]:
        lines = stdout.splitlines()
        if "### GATE_COMMANDS" not in lines:
            return []
        out: list[str] = []
        for ln in lines[lines.index("### GATE_COMMANDS") + 1 :]:
            if ln.startswith("#"):
                break
            if ln.startswith("- "):
                out.append(ln[2:])
        return out

    @staticmethod
    def _three() -> list[dict]:
        return [
            _surface("cli", paths=["src/cli/**"], command="pytest tests/cli"),
            _surface("api", paths=["src/api/**"], command="pytest tests/api"),
            _surface("web", paths=["src/web/**"], command="pytest tests/web"),
        ]


class TestFreeCloseNarrowsOnTheBranchDiff(_FreeCloseResolution):
    def test_a_diff_touching_one_surface_runs_only_its_command(self) -> None:
        out = self._resolve(self._seed(self._three()), "src/cli/main.py")
        self.assertIn("GATE_SCOPE=surface", out)
        self.assertEqual(self._commands(out), ["pytest tests/cli"])
        self.assertNotIn(_FULL, out)

    def test_a_diff_touching_two_of_three_runs_both(self) -> None:
        out = self._resolve(
            self._seed(self._three()), "src/cli/main.py\nsrc/api/routes.py"
        )
        self.assertEqual(self._commands(out), ["pytest tests/cli", "pytest tests/api"])

    def test_an_unclaimed_path_in_the_diff_falls_back(self) -> None:
        """The veto, through the free-close door. A free branch that touches
        something no surface claims must run everything."""
        out = self._resolve(self._seed(self._three()), "src/cli/main.py\nREADME.md")
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])


class TestCollapseWhenTheDiffSelectsEverything(_FreeCloseResolution):
    """The rule that exists because a broad free branch is the common case."""

    def test_touching_every_surface_runs_the_full_command_once(self) -> None:
        """Mutation: drop the collapse check -> red, and this runs THREE
        commands where one was cheaper."""
        out = self._resolve(
            self._seed(self._three()),
            "src/cli/main.py\nsrc/api/routes.py\nsrc/web/app.py",
        )
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])

    def test_a_single_declared_surface_never_collapses(self) -> None:
        """The >=2 floor: with one commanded surface, the narrowed run is
        never slower than the full one, so collapsing would make narrowing
        never fire at all. Mutation: drop the floor -> red."""
        out = self._resolve(
            self._seed([_surface("cli", paths=["src/**"], command="pytest tests/cli")]),
            "src/cli/main.py",
        )
        self.assertIn("GATE_SCOPE=surface", out)
        self.assertEqual(self._commands(out), ["pytest tests/cli"])


class TestFreeClosePreloadEmitsTheBlock(_FreeCloseResolution):
    def test_the_preload_emits_scope_and_a_bounded_block(self) -> None:
        smm = self._seed([])
        env = dict(os.environ)
        env["XP_AGENTS_DATA"] = str(smm.parent.parent)
        env["SMM_DIR"] = str(smm)
        out = subprocess.run(
            ["bash", str(_FREE_CLOSE_PRELOAD)],
            cwd=smm,
            capture_output=True,
            text=True,
            env=env,
        ).stdout
        self.assertIn("GATE_SCOPE=", out)
        self.assertIn("### GATE_COMMANDS", out)
        self.assertEqual(self._commands(out), [_FULL])
        self.assertIn(f"TEST_COMMAND={_FULL}", out)

    def test_nothing_unrelated_sits_inside_the_block(self) -> None:
        """The block is emitted LAST of the preload's own output, so the
        shared reference's first heading bounds it — otherwise the gate would
        'run' that file's prose bullets."""
        smm = self._seed([])
        env = dict(os.environ)
        env["XP_AGENTS_DATA"] = str(smm.parent.parent)
        env["SMM_DIR"] = str(smm)
        out = subprocess.run(
            ["bash", str(_FREE_CLOSE_PRELOAD)],
            cwd=smm,
            capture_output=True,
            text=True,
            env=env,
        ).stdout
        lines = out.splitlines()
        body: list[str] = []
        for ln in lines[lines.index("### GATE_COMMANDS") + 1 :]:
            if ln.startswith("#"):
                break
            body.append(ln)
        stray = [ln for ln in body if ln.strip() and not ln.startswith("- ")]
        self.assertEqual(stray, [], f"non-command lines inside the block: {stray}")


class TestConditionThreeAggregates(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = _FREE_CLOSE_SKILL.read_text()

    def test_condition_three_reads_the_gate_block(self) -> None:
        self.assertIn("### GATE_COMMANDS", self.skill)

    def test_condition_three_names_the_failing_command(self) -> None:
        """Aggregation is only useful if a failure says WHICH command failed —
        otherwise N commands report as one opaque red."""
        self.assertIn("name which command failed", self.skill)

    def test_condition_three_states_the_never_run_nothing_invariant(self) -> None:
        self.assertIn("never run nothing", self.skill)


if __name__ == "__main__":
    unittest.main()
