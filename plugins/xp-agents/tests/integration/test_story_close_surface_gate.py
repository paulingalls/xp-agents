#!/usr/bin/env python3
"""Story-close gate command resolution: surface commands, else the full suite.

Milestone 6's payoff. Condition 3 used to run `stack.test_command` — the whole
suite — before an AUTO-MERGE. It now runs the story's surface commands when
story-015's selection finds any.

WHY THE PRELOAD RESOLVES, NOT THE PROSE. The obvious shape is a decision table
in SKILL.md that the LLM judges. That is the direction conditions 1 and 2 were
converted AWAY from: `tests/skills/test_close_auto_merge_deterministic.py
::test_story_close_no_longer_holds_vacuously` exists because a prose condition
held vacuously and auto-merged anyway. Rebuilding that shape on the same
merge would be strictly worse than the full-suite cost it saves. So the shell
decides and these tests ASSERT the invariant — a gate can never run nothing
and report green.

THE DEAD-TEST TRAP HERE. This repo declares no surface `paths`, so every
assertion below runs against an EMPTY selection unless the fixture seeds one.
That is exactly how story-015's no-match test shipped inert on its first pass.
The surface-path tests therefore seed a surface explicitly, and each states
the mutation that turns it red.
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
_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)

_FULL = "pytest -n auto THE-WHOLE-SUITE"


def _system_context(surfaces: list[dict] | None) -> dict:
    doc: dict = {
        "product": "x",
        "architecture_overview": "x",
        "stack": {"languages": ["Python"], "test_command": _FULL},
        "modules": [],
        "conventions": [],
        "principles": [],
        "project_specific": [],
    }
    if surfaces is not None:
        doc["acceptance_surfaces"] = surfaces
    return doc


def _sprint(file_domain: list[str]) -> dict:
    return {
        "sprint_id": "sprint-test",
        "goal": "gate",
        "started": "2026-08-03",
        "milestone": "test",
        "stories": [
            {
                "id": "story-001",
                "title": "Test",
                "status": "closing",
                "dependencies": [],
                "milestone_ref": "test",
                "design_sources": "test",
                "context": "test",
                "file_domain": file_domain,
                "interface_contracts": [],
                "acceptance_criteria": ["test"],
            }
        ],
    }


class _GateResolutionBase(unittest.TestCase):
    """Drives `emit_gate_commands` directly, so the surface path is exercised
    without standing up a story-shaped git branch."""

    def _seed(self, surfaces: list[dict] | None, file_domain: list[str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        smm = tmp / "data" / "proj" / "smm"
        smm.mkdir(parents=True)
        (smm / "events.jsonl").write_text("")
        (smm / "system_context.json").write_text(json.dumps(_system_context(surfaces)))
        (smm / "sprint.json").write_text(json.dumps(_sprint(file_domain)))
        return smm

    def _resolve(self, smm: Path, story: str = "story-001", full: str = _FULL) -> str:
        script = (
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; SMM_DIR="{smm}"; '
            f'source "{_SURFACE_MODULE}"; '
            f'emit_gate_commands "{story}" "{full}"'
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
        """The `- `-prefixed lines under the block heading."""
        lines = stdout.splitlines()
        if "### GATE_COMMANDS" not in lines:
            return []
        start = lines.index("### GATE_COMMANDS") + 1
        return [ln[2:] for ln in lines[start:] if ln.startswith("- ")]


class TestResolutionPrefersSurfaceCommands(_GateResolutionBase):
    def test_declared_surface_command_replaces_the_full_suite(self) -> None:
        """Mutation: make the resolver ignore surface commands -> red."""
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli",
                }
            ],
            ["src/cli/main.py — the story's only file"],
        )
        out = self._resolve(smm)
        self.assertIn("GATE_SCOPE=surface", out)
        self.assertEqual(self._commands(out), ["pytest tests/cli"])
        self.assertNotIn(_FULL, out)

    def test_two_surfaces_emit_two_runnable_lines(self) -> None:
        """THE `emit_var` refutation, as a test. emit_var's flat() collapses
        whitespace runs, so two commands become one unrunnable string
        (`pytest tests/cli pytest tests/api`). Mutation: emit via emit_var
        instead of the block -> red."""
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest -n auto tests/cli",
                },
                {
                    "name": "api",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/api/**"],
                    "command": "pytest -n auto tests/api",
                },
            ],
            ["src/cli/main.py, src/api/routes.py — both surfaces"],
        )
        out = self._resolve(smm)
        self.assertEqual(
            self._commands(out),
            ["pytest -n auto tests/cli", "pytest -n auto tests/api"],
        )


class TestResolutionFallsBackToTheFullSuite(_GateResolutionBase):
    def test_no_surface_declares_paths_falls_back(self) -> None:
        """Every project's state today. Mutation: resolver returns surface
        commands only, never the fallback -> red."""
        smm = self._seed(
            [{"name": "cli", "signals": ["x"], "status": "covered"}],
            ["src/cli/main.py"],
        )
        out = self._resolve(smm)
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])

    def test_partial_coverage_falls_back(self) -> None:
        """story-015 vetoes a partly-claimed domain, so the gate must see
        'no narrowing' and run everything — NOT run the one claimed
        surface and merge green on a file nothing tested."""
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli",
                }
            ],
            ["src/cli/main.py, src/db/schema.py — db is unclaimed"],
        )
        out = self._resolve(smm)
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])

    def test_no_story_id_falls_back(self) -> None:
        smm = self._seed(None, ["src/cli/main.py"])
        out = self._resolve(smm, story="")
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])


class TestSelectionExpandsGlobsUnderTheGivenCwd(_GateResolutionBase):
    """`commands_for_story` expands a glob file_domain over DISK, so which
    checkout it looks at is load-bearing. On a teammate close the story's new
    files exist only in the worktree; computing against the main checkout
    yields empty — which FAILS SAFE, and that is what makes it dangerous:
    the feature would be permanently, undetectably inert.
    """

    def _tree(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        (root / "src" / "cli").mkdir(parents=True)
        (root / "src" / "cli" / "main.py").write_text("")
        return root

    def _smm(self) -> Path:
        return self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli",
                }
            ],
            ["src/**/main.py — a GLOB, so it only expands where the file is"],
        )

    def _resolve_at(self, smm: Path, cwd: str) -> str:
        script = (
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; SMM_DIR="{smm}"; '
            f'source "{_SURFACE_MODULE}"; '
            f'emit_gate_commands "story-001" "{_FULL}" "{cwd}"'
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_cwd_argument_is_honored(self) -> None:
        """Mutation: hardcode `--cwd .` in find_surface_commands -> red."""
        smm = self._smm()
        found = self._resolve_at(smm, str(self._tree()))
        self.assertEqual(self._commands(found), ["pytest tests/cli"])

    def test_the_wrong_checkout_yields_the_full_fallback(self) -> None:
        smm = self._smm()
        empty_root = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(empty_root, ignore_errors=True)
        )
        missed = self._resolve_at(smm, str(empty_root))
        self.assertEqual(self._commands(missed), [_FULL])

    def test_the_preload_passes_the_teammate_cwd(self) -> None:
        """Source pin: the behavioral tests above prove the parameter works,
        but only the call site decides which checkout it names. The sibling
        verify_paths call in the same file already uses this expression."""
        source = _STORY_CLOSE_PRELOAD.read_text()
        self.assertIn('emit_gate_commands "$STORY_ID"', source)
        self.assertRegex(
            source,
            r'emit_gate_commands "\$STORY_ID".*\$\{TEAMMATE_CWD:-\.\}',
        )


class TestTheGateCanNeverRunNothingAndReportGreen(_GateResolutionBase):
    """The invariant that matters — condition 3 guards an AUTO-merge."""

    def test_scope_none_emits_no_block_at_all(self) -> None:
        """No surfaces AND no test_command: the block must be ABSENT, so the
        skill's single branch cannot find commands and falls through to the
        confirm prompt."""
        smm = self._seed(None, ["src/cli/main.py"])
        out = self._resolve(smm, full="")
        self.assertIn("GATE_SCOPE=none", out)
        self.assertNotIn("### GATE_COMMANDS", out)

    def test_a_non_none_scope_always_carries_at_least_one_command(self) -> None:
        """Mutation: emit GATE_SCOPE=full with an empty block -> red. An
        emitted-but-empty block is the shape that would run nothing and let
        the merge proceed."""
        for surfaces, domain, full in (
            (None, ["src/cli/main.py"], _FULL),
            ([{"name": "c", "signals": ["x"], "status": "covered"}], ["a.py"], _FULL),
            (
                [
                    {
                        "name": "c",
                        "signals": ["x"],
                        "status": "covered",
                        "paths": ["src/**"],
                        "command": "pytest tests/c",
                    }
                ],
                ["src/a.py"],
                _FULL,
            ),
        ):
            with self.subTest(domain=domain):
                out = self._resolve(self._seed(surfaces, domain), full=full)
                scope = next(
                    ln.split("=", 1)[1]
                    for ln in out.splitlines()
                    if ln.startswith("GATE_SCOPE=")
                )
                if scope != "none":
                    self.assertTrue(
                        self._commands(out),
                        f"GATE_SCOPE={scope} with no commands would run nothing",
                    )


class TestStoryClosePreloadEmitsTheGateBlock(unittest.TestCase):
    """End-to-end through the real preload, on the shape every project is in
    today: no surface declares paths, so the gate falls back and says so."""

    def test_preload_emits_scope_and_block(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        smm = tmp / "data" / "proj" / "smm"
        smm.mkdir(parents=True)
        (smm / "events.jsonl").write_text("")
        (smm / "system_context.json").write_text(json.dumps(_system_context(None)))
        env = dict(os.environ)
        env["XP_AGENTS_DATA"] = str(smm.parent.parent)
        env["SMM_DIR"] = str(smm)
        out = subprocess.run(
            ["bash", str(_STORY_CLOSE_PRELOAD)],
            cwd=smm,
            capture_output=True,
            text=True,
            env=env,
        ).stdout
        self.assertIn("GATE_SCOPE=", out)
        self.assertIn("### GATE_COMMANDS", out)
        self.assertIn(f"- {_FULL}", out)
        # TEST_COMMAND stays emitted verbatim — existing consumers untouched.
        self.assertIn(f"TEST_COMMAND={_FULL}", out)


if __name__ == "__main__":
    unittest.main()
