#!/usr/bin/env python3
"""What the close gate block may contain, and when it may exist at all.

Both close SKILL.md files tell the agent to run **every** command in the
`### GATE_COMMANDS` block and then MERGE WITHOUT ASKING. That makes two
properties of the block safety properties rather than formatting ones:

1. A DECLARED COMMAND'S FAILURE MUST REACH THE GATE. This heading used to read
   "one command per bullet", and that framing was wrong in a way that let a
   defect ship with a comment claiming it was fixed. Flattening newlines gives
   one BULLET; it says nothing about how the shell executes it. `\\n;`
   flattens to `pytest -q ; echo X` — one bullet, two commands — and a bare
   `;` never needed a newline.

   The property that actually matters here is greenness: `pytest -q; echo done`
   exits 0 when pytest FAILED, so the gate reads pass and auto-merges a red
   suite. `close_gate_commands` refuses any command whose own exit status does
   not reach the shell (`shell_exit_structure.exit_reaches_shell`), emitting no
   block and a reason. `&&` propagates failure and is accepted.

2. THE DOCUMENTED OPT-OUT STILL DISABLES THE GATE. PROCESS_GUIDE says an
   empty `stack.test_command` disables the close auto-merge, and both
   SKILL.md files print "set stack.test_command ... to enable" when no block
   is emitted. Resolving surface commands FIRST re-armed unattended merging
   for a project that switched it off on purpose.

The harness drives `emit_gate_commands` through the real shell module and the
real `close_gate_commands` resolver — the two files this file guards.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _bases import _PLUGIN_ROOT
from _gate_harness import CLAIMED as _CLAIMED
from _gate_harness import GateHarness


class _BlockHarness(GateHarness):
    """Naming shim over the shared harness — see `_gate_harness`.

    This file's env-passing shape is the one the consolidation KEPT, because
    it is the only one that can carry the newline-, quote- and
    separator-bearing commands these safety assertions are about.
    """

    def _seed(self, surfaces: list[dict], test_command: str) -> Path:
        return self.seed(surfaces, test_command=test_command)

    def _resolve(self, smm: Path, *, paths: str, full: str) -> str:
        return self.resolve(smm, paths=paths, full=full)

    _commands = staticmethod(GateHarness.commands)
    _scope = staticmethod(GateHarness.scope)


class TestOneBulletIsOneCommand(_BlockHarness):
    """A newline may never become a second command the gate executes."""

    def test_a_newline_in_test_command_yields_no_block_at_all(self) -> None:
        """SUPERSEDED ASSERTION, deliberately rewritten — read this before
        "fixing" it back.

        This test used to assert `scope=full` with a single flattened bullet,
        `pytest -q rm -rf build`. That was the weaker property, and it was
        wrong twice over: it declared a two-line command "safe" by mashing it
        into one nonsense command that cannot run, and it left `\\n;` — which
        flattens to `pytest -q ; echo X` — passing as one bullet that the
        shell then executes as two.

        The stronger property: a declared command whose own exit status does
        not reach the shell is REFUSED. Two lines is two commands, so the
        honest answer is no block and a reason, not a mashed-together string.

        Mutation: flatten before the exit-status check instead of after -> red.
        """
        smm = self._seed([], "pytest -q\nrm -rf build")
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -q\nrm -rf build")
        self.assertEqual(self._scope(out), "none")
        self.assertEqual(self._commands(out), [])
        self.assertNotIn("rm -rf build", out)

    def test_a_newline_in_a_surface_command_collapses_the_leg(self) -> None:
        """SUPERSEDED, like the full-command case above. This asserted
        `scope=surface` with a mashed `pytest tests/cli rm -rf build` — a
        command that cannot run, declared "safe" because it was one bullet.

        Two lines is two commands, so the surface command is REFUSED, and
        refusal collapses the whole leg to the full suite rather than filtering
        (concern 96002de2ca73). Mutation: filter instead of collapse -> red,
        and `src/cli/**` is covered by nothing.
        """
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
        self.assertEqual(self._scope(out), "full")
        self.assertEqual(self._commands(out), ["pytest -n auto WHOLE-SUITE"])
        self.assertNotIn("rm -rf build", out)

    def test_a_carriage_return_in_a_surface_command_collapses_the_leg(self) -> None:
        """A CRLF-authored document must not smuggle one in either."""
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
        self.assertEqual(self._scope(out), "full")
        self.assertNotIn("rm -rf build", out)


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
        # `selected` drops the drift-recheck bullet, which is machinery rather
        # than a chosen test command — see TestTheDriftRecheckBullet.
        self.assertEqual(self.selected(out), ["pytest tests/cli"])


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

    def test_the_no_block_hint_reads_the_reason_instead_of_guessing(self) -> None:
        """SUPERSEDED ASSERTION. This used to require the literal sentence
        "Auto-merge disabled — set stack.test_command ... to enable", printed
        whenever no block existed.

        That sentence became a lie the moment refusal was added as a third
        no-block condition: a user who declared `make test | tee log` HAS set
        the field, and would be told to set it. Same claim-vs-coverage defect
        this module exists to catch, so it is fixed rather than pinned.

        Both skills now report the preload's `GATE_DISABLED_REASON` and
        distinguish the two causes. Mutation: collapse them to one message, or
        go back to assuming unset -> red.
        """
        for skill in ("xp-story-close", "xp-free-close"):
            with self.subTest(skill=skill):
                text = (_PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text()
                self.assertIn("GATE_DISABLED_REASON", text)
                self.assertIn("not-set", text)
                self.assertIn("exit-status-masked", text)
                # The preload's own reason for "the resolver did not answer" —
                # a cause with the field SET, so it needs its own sentence or
                # the hint is back to guessing.
                self.assertIn("unresolved", text)
                self.assertIn("edit-stack-field test_command", text)


class TestACommandWhoseFailureCannotReachTheGate(_BlockHarness):
    """concern 50cde7648f7f — a GREENNESS defect, not mainly an injection one.

        pytest -q; echo done     exits 0 even when pytest FAILED

    Condition 3 reads that as pass and merges without asking, so a red suite
    auto-merges. Which operators discard an exit status is decidable from the
    string alone, and `shell_exit_structure.exit_reaches_shell` already decides
    it — shipped by story-003 in this same sprint, never wired to this consumer.

    Flattening was never a defense against this. `flat()` closed the UNADORNED
    newline only; `\\n;` collapses to `pytest -q ; echo PWNED` — one bullet,
    two executed commands — and bare `;`/`&`/`|` never went through it at all.
    A close review found that by RUNNING the shipped function while three
    comments claimed the block was safe.
    """

    def test_a_semicolon_joined_command_is_refused(self) -> None:
        """Mutation: drop the exit_reaches_shell check -> red, and a failing
        pytest auto-merges."""
        out = self._resolve(
            self._seed([], "irrelevant"), paths=_CLAIMED, full="pytest -q; echo done"
        )
        self.assertEqual(self._scope(out), "none")
        self.assertEqual(self._commands(out), [])

    def test_an_and_joined_command_is_still_accepted(self) -> None:
        """The discriminating partner: `&&` PROPAGATES failure, so refusing it
        would be over-refusal that disables the gate for a normal command.
        Mutation: refuse every compound -> red."""
        out = self._resolve(
            self._seed([], "irrelevant"),
            paths=_CLAIMED,
            full="pytest -q && ruff check",
        )
        self.assertEqual(self._scope(out), "full")
        self.assertEqual(self._commands(out), ["pytest -q && ruff check"])

    def test_the_close_review_transcript_no_longer_yields_two_commands(self) -> None:
        """The exact input from the close review, kept verbatim as a pin."""
        out = self._resolve(
            self._seed([], "irrelevant"),
            paths=_CLAIMED,
            full="pytest -q\n; echo PWNED",
        )
        self.assertEqual(self._scope(out), "none")
        self.assertNotIn("echo PWNED", out)

    def test_one_masked_surface_command_collapses_the_WHOLE_leg(self) -> None:
        """All-or-nothing, never a filter (concern 96002de2ca73). The veto has
        already proved every changed path is claimed; dropping just the refused
        command would leave that surface's paths running nowhere while the gate
        reports green — the fail-open shape this story exists to close.

        Mutation: filter the refused command out of the set instead of
        collapsing -> red, and `src/api/routes.py` is tested by nothing.

        A THIRD commanded surface is declared and NOT touched, so the two
        selected ones are a strict subset. Without it this test passes
        vacuously: selecting every declared command collapses to the full
        suite by design, which produces the expected output for a reason that
        has nothing to do with refusal. (Measured — it did.)
        """
        smm = self._seed(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/cli/**"],
                    "command": "pytest tests/cli; echo ok",
                },
                {
                    "name": "api",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/api/**"],
                    "command": "pytest tests/api",
                },
                {
                    "name": "web",
                    "signals": ["x"],
                    "status": "covered",
                    "paths": ["src/web/**"],
                    "command": "pytest tests/web",
                },
            ],
            "pytest -n auto WHOLE-SUITE",
        )
        out = self._resolve(
            smm,
            paths="src/cli/main.py\nsrc/api/routes.py",
            full="pytest -n auto WHOLE-SUITE",
        )
        self.assertEqual(self._scope(out), "full")
        self.assertEqual(self._commands(out), ["pytest -n auto WHOLE-SUITE"])


class TestTheDisabledReasonDistinguishesUnsetFromUnusable(_BlockHarness):
    """concern 345503125704. Refusal is a THIRD no-block condition, and both
    SKILL.md hints say "set stack.test_command ... to enable" whenever no block
    is emitted. A user who declared `make test | tee log` HAS set it and would
    read a false message — the same claim-vs-coverage defect being corrected
    elsewhere in this story. The preload emits the reason; the prose prints it.
    """

    def test_an_unset_command_reports_not_set(self) -> None:
        out = self._resolve(self._seed([], ""), paths=_CLAIMED, full="")
        self.assertIn("GATE_DISABLED_REASON=not-set", out)

    def test_a_masked_command_reports_exit_status_masked(self) -> None:
        """Mutation: emit one reason for both -> red, and the hint lies."""
        out = self._resolve(
            self._seed([], "irrelevant"), paths=_CLAIMED, full="pytest -q | tee log"
        )
        self.assertIn("GATE_DISABLED_REASON=exit-status-masked", out)

    def test_a_resolver_that_cannot_ANSWER_reports_unresolved(self) -> None:
        """The third cause, and the one the preload owns rather than the
        resolver: the script did not answer at all. A corrupt
        system_context.json raises inside it, and the field it would have read
        may be perfectly well set.

        Mutation: fall back to `not-set` -> red, and the prose tells a user
        with a declared `stack.test_command` to go and declare it.
        """
        smm = self._seed([], "pytest -q")
        (smm / "system_context.json").write_text("{ not json")
        out = self._resolve(smm, paths=_CLAIMED, full="pytest -q")
        self.assertEqual(self._scope(out), "none")
        self.assertIn("GATE_DISABLED_REASON=unresolved", out)
        self.assertNotIn("### GATE_COMMANDS", out)

    def test_no_reason_is_emitted_when_a_block_exists(self) -> None:
        """The variable exists to explain an ABSENT block. Emitting it beside a
        present one would invite the prose to print a disabled hint next to
        runnable commands."""
        out = self._resolve(
            self._seed([], "irrelevant"), paths=_CLAIMED, full="pytest -q"
        )
        self.assertEqual(self._scope(out), "full")
        self.assertNotIn("GATE_DISABLED_REASON", out)


if __name__ == "__main__":
    unittest.main()
