#!/usr/bin/env python3
"""What the close gate block may contain, and when it may exist at all.

Both close SKILL.md files tell the agent to run **every** command in the
`### GATE_COMMANDS` block and then MERGE WITHOUT ASKING. That makes two
properties of the block safety properties rather than formatting ones:

1. ONE COMMAND PER BULLET. The block's producer splits on newlines, so a
   newline anywhere in a declared command (`stack.test_command`, or a
   surface's `command`) becomes a SECOND EXECUTED COMMAND at an unattended
   merge. Nothing in the schema rejects one — both fields are only type- and
   length-checked. The old `emit_var`/`flat()` path collapsed newlines to
   spaces and so had one command by construction; the block re-opened the
   door, and it is closed here on BOTH legs (the full command in
   `emit_gate_commands`, the surface command in
   `surface_selection._declared_command`).

2. THE DOCUMENTED OPT-OUT STILL DISABLES THE GATE. PROCESS_GUIDE says an
   empty `stack.test_command` disables the close auto-merge, and both
   SKILL.md files print "set stack.test_command ... to enable" when no block
   is emitted. Resolving surface commands FIRST re-armed unattended merging
   for a project that switched it off on purpose.

The harness drives `emit_gate_commands` through the real shell module and the
real `surface-commands` CLI — the two files this file guards.
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

_CLAIMED = "src/cli/main.py"


class _BlockHarness(unittest.TestCase):
    def _seed(self, surfaces: list[dict], test_command: str) -> Path:
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
                    "stack": {"languages": ["Python"], "test_command": test_command},
                    "modules": [],
                    "conventions": [],
                    "principles": [],
                    "project_specific": [],
                    "acceptance_surfaces": surfaces,
                }
            )
        )
        return smm

    def _resolve(self, smm: Path, *, paths: str, full: str) -> str:
        """Values travel by ENV, never interpolated into the bash source.

        A newline in `full` is the whole point of these tests; splicing it
        into a `bash -c` string would make the TEST forge a second shell line
        and prove nothing about the code under test.
        """
        script = (
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; SMM_DIR="{smm}"; '
            f'source "{_SURFACE_MODULE}"; '
            'emit_gate_commands "$XP_T_PATHS" "$XP_T_FULL"'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SMM_DIR": str(smm),
                "XP_T_PATHS": paths,
                "XP_T_FULL": full,
            },
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
    def _scope(stdout: str) -> str:
        return next(
            ln.split("=", 1)[1]
            for ln in stdout.splitlines()
            if ln.startswith("GATE_SCOPE=")
        )


class TestOneBulletIsOneCommand(_BlockHarness):
    """A newline may never become a second command the gate executes."""

    def test_a_newline_in_test_command_stays_one_bullet(self) -> None:
        """Mutation: drop `flat` from emit_gate_commands's fallback leg -> red,
        because `rm -rf build` arrives as its own bullet and condition 3 runs
        every bullet."""
        smm = self._seed([], "pytest -q\nrm -rf build")
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -q\nrm -rf build")
        self.assertEqual(self._scope(out), "full")
        self.assertEqual(self._commands(out), ["pytest -q rm -rf build"])

    def test_a_newline_in_a_surface_command_stays_one_bullet(self) -> None:
        """The same door on the surface leg. Mutation: return `command`
        unflattened from `surface_selection._declared_command` -> red."""
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli\nrm -rf build",
                }
            ],
            "pytest -n auto WHOLE-SUITE",
        )
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -n auto WHOLE-SUITE")
        self.assertEqual(self._scope(out), "surface")
        self.assertEqual(self._commands(out), ["pytest tests/cli rm -rf build"])

    def test_a_carriage_return_in_a_surface_command_stays_one_bullet(self) -> None:
        """`str.split()` covers \\r and \\t as well as \\n; a CRLF-authored
        document must not smuggle one in either."""
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli\r\nrm -rf build",
                }
            ],
            "pytest -n auto WHOLE-SUITE",
        )
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -n auto WHOLE-SUITE")
        self.assertEqual(self._commands(out), ["pytest tests/cli rm -rf build"])


class TestTheDocumentedOptOutStillDisablesTheGate(_BlockHarness):
    """PROCESS_GUIDE: an empty `stack.test_command` disables the auto-merge."""

    def test_declared_surfaces_do_not_re_arm_an_empty_test_command(self) -> None:
        """Mutation: resolve surface commands BEFORE the fallback -> red. The
        project switched auto-merge off; declaring a surface must not switch
        it back on."""
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
            "",
        )
        out = self._resolve(smm, paths=_CLAIMED, full="")
        self.assertEqual(self._scope(out), "none")
        self.assertNotIn("### GATE_COMMANDS", out)

    def test_a_whitespace_only_test_command_is_still_the_off_switch(self) -> None:
        """The same input by the other door: `"   "` is not a runnable
        command, so it is not an opt-IN either."""
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
            "   ",
        )
        out = self._resolve(smm, paths=_CLAIMED, full="   ")
        self.assertEqual(self._scope(out), "none")
        self.assertNotIn("### GATE_COMMANDS", out)

    def test_narrowing_still_fires_when_the_full_command_is_set(self) -> None:
        """The refutation of the two above: the opt-out check must not have
        disabled narrowing outright. Mutation: return `none` unconditionally
        -> red."""
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
            "pytest -n auto WHOLE-SUITE",
        )
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -n auto WHOLE-SUITE")
        self.assertEqual(self._scope(out), "surface")
        self.assertEqual(self._commands(out), ["pytest tests/cli"])


class TestBothCloseSkillsRunEveryBullet(unittest.TestCase):
    """Why the two classes above are SAFETY tests and not formatting ones:
    the prose the block feeds runs every bullet and then merges unasked."""

    def test_each_close_skill_says_every_command(self) -> None:
        for skill in ("xp-story-close", "xp-free-close"):
            with self.subTest(skill=skill):
                text = (_PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text()
                self.assertIn("### GATE_COMMANDS", text)
                # Free-close bolds the word (`**every**`), story-close does
                # not — match the part neither spells differently.
                self.assertIn("command in it", text)

    def test_the_off_switch_hint_still_names_test_command(self) -> None:
        """The hint printed when no block exists. If surfaces could arm the
        gate on their own, this sentence would be false — which is what makes
        the ordering in `emit_gate_commands` a contract."""
        for skill in ("xp-story-close", "xp-free-close"):
            with self.subTest(skill=skill):
                text = (_PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text()
                self.assertIn("Auto-merge disabled — set stack.test_command", text)


if __name__ == "__main__":
    unittest.main()
