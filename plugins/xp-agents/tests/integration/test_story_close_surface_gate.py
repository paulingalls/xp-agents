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

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _bases import _PLUGIN_ROOT
from _gate_harness import FULL as _FULL
from _gate_harness import GateHarness

_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)


class _GateResolutionBase(GateHarness):
    """Naming shim over the shared harness — see `_gate_harness`.

    Values now travel by ENV instead of being interpolated into the bash
    source. This harness previously could not express a newline-, quote- or
    separator-bearing command at all; any assertion whose RESULT changed under
    the switch is a finding, not a diff to smooth over.
    """

    def _seed(self, surfaces: list[dict] | None, file_domain: list[str]) -> Path:
        return self.seed(surfaces, file_domain=file_domain)

    def _resolve(
        self, smm: Path, *, paths: str = "src/cli/main.py", full: str = _FULL
    ) -> str:
        return self.resolve(smm, paths=paths, full=full)

    _commands = staticmethod(GateHarness.commands)


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
        out = self._resolve(smm, paths="src/cli/main.py")
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
                # A third commanded surface so selecting two is a SUBSET —
                # selecting every command collapses to the full suite by
                # design, which would mask what this test is about.
                {
                    "name": "web",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/web/**"],
                    "command": "pytest -n auto tests/web",
                },
            ],
            ["src/cli/main.py, src/api/routes.py — both surfaces"],
        )
        out = self._resolve(smm, paths="src/cli/main.py\nsrc/api/routes.py")
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
        out = self._resolve(smm, paths="src/cli/main.py\nsrc/db/schema.py")
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])

    def test_no_story_id_falls_back(self) -> None:
        smm = self._seed(None, ["src/cli/main.py"])
        out = self._resolve(smm, paths="")
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])


class TestSelectionSeesDriftedFiles(_GateResolutionBase):
    """AC6 / concern 97ea86f85c80. Step 1b tolerates file_domain drift and
    continues, so the DECLARED domain is not what the story changed. Selecting
    on the declaration let a drifted file skip the coverage veto entirely and
    run its tests nowhere — at an auto-merge. Selection now takes the close
    diff, so the declaration cannot hide anything.
    """

    def test_a_drifted_path_outside_the_declared_domain_still_vetoes(self) -> None:
        """Mutation: select on the declared file_domain instead of the diff
        -> red. The story declares ONLY the claimed file; the diff also holds
        an unclaimed one."""
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
            ["src/cli/main.py — the ONLY declared file"],
        )
        out = self._resolve(smm, paths="src/cli/main.py\nsrc/db/drifted.py")
        self.assertIn("GATE_SCOPE=full", out)
        self.assertEqual(self._commands(out), [_FULL])

    def test_a_drifted_path_inside_a_surface_still_narrows(self) -> None:
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
            ["src/cli/main.py — the ONLY declared file"],
        )
        out = self._resolve(smm, paths="src/cli/main.py\nsrc/cli/drifted.py")
        self.assertIn("GATE_SCOPE=surface", out)
        self.assertEqual(self._commands(out), ["pytest tests/cli"])


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

    def test_a_whitespace_only_command_is_not_a_command(self) -> None:
        """`stack.test_command` set to blanks passed the old condition 3? No —
        `emit_var`'s flat() trimmed it to empty and auto-merge stayed off. The
        block prints the value RAW, so without a runnability filter the same
        input yields `GATE_SCOPE=full` plus a bullet holding nothing: the gate
        runs nothing and merges green. Nothing in the schema rejects it
        (`command`/`test_command` are only type- and length-checked).
        """
        smm = self._seed(None, ["src/cli/main.py"])
        out = self._resolve(smm, full="   ")
        self.assertIn("GATE_SCOPE=none", out)
        self.assertNotIn("### GATE_COMMANDS", out)

    def test_a_blank_surface_command_drops_out_of_the_set(self) -> None:
        """Same input by the other door. A blank surface command contributes
        nothing — exactly like the declared-no-command surface that
        `surface_selection` already treats as coverage without a run — instead
        of an unrunnable bullet its siblings' green would carry.
        """
        smm = self._seed(
            [
                {
                    "name": "blank",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/a.py"],
                    "command": "  ",
                },
                {
                    "name": "real",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/b.py"],
                    "command": "pytest tests/b",
                },
            ],
            ["src/a.py, src/b.py"],
        )
        out = self._resolve(smm, paths="src/a.py\nsrc/b.py")
        self.assertIn("GATE_SCOPE=surface", out)
        self.assertEqual(self._commands(out), ["pytest tests/b"])

    def test_a_non_none_scope_always_carries_at_least_one_command(self) -> None:
        """Mutation: emit GATE_SCOPE=full with an empty block -> red. An
        emitted-but-empty block is the shape that would run nothing and let
        the merge proceed.

        Every case below hands in a runnable `full`, so `none` is not a legal
        answer for any of them — asserted, not skipped. Guarding the real
        assertion on `if scope != "none"` would let a resolver that answered
        `none` everywhere pass this test with nothing checked, which is the
        vacuous shape the whole class exists to rule out.
        """
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
                self.assertNotEqual(scope, "none", "a runnable full command was set")
                self.assertTrue(
                    self._commands(out),
                    f"GATE_SCOPE={scope} with no commands would run nothing",
                )


class TestConditionThreeConsumesTheResolvedSet(unittest.TestCase):
    """The prose half. Condition 3 must read the block the preload resolved,
    NOT re-derive the surface-vs-full choice itself — a decision table here is
    the vacuous-hold shape conditions 1 and 2 were converted away from.
    """

    def setUp(self) -> None:
        self.skill = (_PLUGIN_ROOT / "skills/xp-story-close/SKILL.md").read_text()

    def test_condition_three_reads_the_gate_block(self) -> None:
        self.assertIn("### GATE_COMMANDS", self.skill)

    def test_condition_three_states_the_never_run_nothing_invariant(self) -> None:
        self.assertIn("never run nothing", self.skill)

    def test_condition_three_does_not_re_derive_the_choice(self) -> None:
        """No surface-vs-full branching in prose: the preload already chose,
        and GATE_SCOPE is reporting only."""
        self.assertNotIn("when nothing matched", self.skill)
        self.assertNotIn("falling back to the full", self.skill)


class TestStoryClosePreloadEmitsTheGateBlock(GateHarness):
    """End-to-end through the real preload, on the shape every project is in
    today: no surface declares paths, so the gate falls back and says so."""

    def test_preload_emits_scope_and_block(self) -> None:
        out = self._real_preload_stdout()
        self.assertIn("GATE_SCOPE=", out)
        self.assertIn("### GATE_COMMANDS", out)
        self.assertIn(f"- {_FULL}", out)
        # TEST_COMMAND stays emitted verbatim — existing consumers untouched.
        self.assertIn(f"TEST_COMMAND={_FULL}", out)

    def test_the_block_is_not_polluted_by_the_shared_reference(self) -> None:
        """The preload appends `_close_pipeline_shared.md`, which carries its
        own `- ` bullets (the Step 5c classifier list). The gate block is
        emitted LAST of the preload's own output so the next markdown heading
        bounds it — otherwise the gate would 'run' a dozen prose bullets.
        """
        out = _GateResolutionBase._commands(self._real_preload_stdout())
        self.assertEqual(out, [_FULL])

    def test_nothing_unrelated_sits_inside_the_block(self) -> None:
        """The block must be the LAST of the preload's own output, so its
        section holds commands and nothing else. Emitted earlier, `REVIEW_PATH=`
        and `SYSTEM_CONTEXT_RENDERED=` fall INSIDE the section — the previous
        assertion cannot see that, because it only collects `- ` lines.
        """
        lines = self._real_preload_stdout().splitlines()
        start = lines.index("### GATE_COMMANDS") + 1
        body: list[str] = []
        for ln in lines[start:]:
            if ln.startswith("#"):
                break
            body.append(ln)
        stray = [ln for ln in body if ln.strip() and not ln.startswith("- ")]
        self.assertEqual(stray, [], f"non-command lines inside the block: {stray}")

    def test_the_preload_passes_the_close_diff(self) -> None:
        """Source pin: only the call site names the input. Replaced with "",
        the whole suite still passed (measured) while narrowing was inert."""
        self.assertIn(
            'emit_gate_commands "$(get_changed_files_range "${TARGET_BRANCH}")"',
            _STORY_CLOSE_PRELOAD.read_text(),
        )

    def _real_preload_stdout(self) -> str:
        smm = self.seed(None)
        env = dict(os.environ)
        env["XP_AGENTS_DATA"] = str(smm.parent.parent)
        env["SMM_DIR"] = str(smm)
        return subprocess.run(
            ["bash", str(_STORY_CLOSE_PRELOAD)],
            cwd=smm,
            capture_output=True,
            text=True,
            env=env,
        ).stdout


if __name__ == "__main__":
    unittest.main()
