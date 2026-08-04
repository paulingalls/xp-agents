#!/usr/bin/env python3
"""The drift recheck: the bullet that re-derives the gate's own command set.

Extracted from `test_close_gate_command_hygiene.py`, which crossed the 500-line
cap when these landed. Cohesive group: the hygiene file asks what a block may
CONTAIN, this one asks whether the block still covers the branch by the time it
runs.

THE DEFECT (concern 85e85c1a2ac7). The command set is resolved once, in the
preload, from the PRE-REVIEW diff. Step 5c review fixes land after that, and
both close SKILL.md files forbid re-deriving the set in prose — correctly, since
a gate decided in prose cannot be asserted; that is the vacuous-hold shape
conditions 1 and 2 were converted away from. So a file first touched by a review
fix could be covered by no selected command while condition 3 reported green and
merged unasked.

THE FIX. Re-derivation becomes a COMMAND IN THE BLOCK. Condition 3 already
requires every command to exit 0, so the existing contract enforces the freeze
with no new prose at all. Failure direction is right by construction: drift
exits non-zero, condition 3 fails, and the close falls through to the human
prompt. It can never fail toward auto-merge.

WHAT IS DIGESTED, and why it matters: the resolved COMMAND SET, not the diff. A
review fix touching a file already inside a selected surface changes the diff
but not what must run, so it passes. Only a change to what must RUN trips it.
Digesting the diff instead would send every review fix to the human prompt and
the feature would be switched off as flaky.

THE DEAD-TEST TRAP: no project declares surface `paths`, so an assertion that
forgets to seed one runs against an empty selection, never narrows, and never
emits a recheck bullet at all — passing vacuously.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _gate_harness import CLAIMED as _CLAIMED
from _gate_harness import GateHarness


class _BlockHarness(GateHarness):
    """Same naming shim as the hygiene suite — see `_gate_harness`."""

    def _seed(self, surfaces: list[dict], test_command: str) -> Path:
        return self.seed(surfaces, test_command=test_command)

    def _resolve(self, smm: Path, *, paths: str, full: str) -> str:
        return self.resolve(smm, paths=paths, full=full)

    _commands = staticmethod(GateHarness.commands)
    _scope = staticmethod(GateHarness.scope)


class TestTheDriftRecheckBullet(_BlockHarness):
    """concern 85e85c1a2ac7. The command set is frozen at preload time, and
    both SKILL.md files forbid re-deriving it in prose — correctly, since a
    gate decided in prose cannot be asserted. So the re-derivation is a COMMAND
    IN THE BLOCK: condition 3 already requires every command to exit 0, which
    makes the existing contract enforce the freeze with no new prose.
    """

    _SURFACE: ClassVar[dict] = {
        "name": "cli",
        "signals": ["x"],
        "status": "covered",
        "paths": ["src/cli/**"],
        "command": "pytest tests/cli",
    }

    def test_it_is_emitted_first_under_surface_scope(self) -> None:
        """First is fail-fast, not the enforcement mechanism — but a cheap
        check before a long suite is worth having. Mutation: emit it last ->
        red."""
        out = self._resolve(
            self._seed([self._SURFACE], "pytest -n auto WHOLE-SUITE"),
            paths=_CLAIMED,
            full="pytest -n auto WHOLE-SUITE",
        )
        self.assertEqual(self._scope(out), "surface")
        self.assertIn("--expect-digest", self._commands(out)[0])

    def test_it_is_absent_under_full_scope(self) -> None:
        """Every project on disk today is here, and its block must be
        unchanged. Under `full` there is nothing to recheck: the full command
        is the maximum, so a later fix cannot make it insufficient. Mutation:
        emit it on the full leg too -> red."""
        out = self._resolve(
            self._seed([], "pytest -n auto WHOLE-SUITE"),
            paths=_CLAIMED,
            full="pytest -n auto WHOLE-SUITE",
        )
        self.assertEqual(self._scope(out), "full")
        self.assertIsNone(self.recheck(out))

    def test_its_paths_are_absolute_and_quoted(self) -> None:
        """The agent runs this bullet in ITS shell, where PLUGIN_ROOT and
        SMM_DIR do not exist and a worktree path may hold spaces. Mutation:
        interpolate bare -> red on the space-bearing SMM path."""
        out = self._resolve(
            self._seed([self._SURFACE], "pytest -n auto WHOLE-SUITE"),
            paths=_CLAIMED,
            full="pytest -n auto WHOLE-SUITE",
        )
        bullet = self._assert_not_none(self.recheck(out))
        self.assertNotIn("${PLUGIN_ROOT}", bullet)
        self.assertNotIn("${SMM_DIR}", bullet)
        self.assertIn("/scripts/close_gate_commands.py", bullet)


class TestTheRecheckDetectsDrift(_BlockHarness):
    """AC1/AC2 — the case story-018 exists for.

    Step 5c review fixes land AFTER the preload froze the command set, and the
    prose is forbidden from re-deriving it. So the frozen set can stop covering
    the branch while condition 3 still reports green and merges unasked. The
    recheck bullet re-derives from the CURRENT diff and fails on drift.
    """

    _SURFACES: ClassVar[list] = [
        {
            "name": "cli",
            "signals": ["x"],
            "status": "covered",
            "paths": ["src/cli/**"],
            "command": "pytest tests/cli",
        },
        {
            "name": "docs",
            "signals": ["x"],
            "status": "covered",
            "paths": ["docs/**"],
        },
    ]

    def _armed_recheck(self) -> tuple[str, Path]:
        out = self._resolve(
            self._seed(self._SURFACES, "pytest -n auto WHOLE-SUITE"),
            paths="src/cli/main.py",
            full="pytest -n auto WHOLE-SUITE",
        )
        self.assertEqual(self._scope(out), "surface")
        # `_assert_not_none` narrows for pyright, so no second bare assert
        # (test_assert_not_none_pin forbids the two-line form).
        return self._assert_not_none(self.recheck(out)), self.last_repo

    def _run(self, bullet: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-c", bullet], capture_output=True, text=True)

    def _commit(self, repo: Path, rel: str) -> None:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        for args in (["add", "-A"], ["commit", "-m", "review fix"]):
            subprocess.run(["git", "-C", str(repo), *args], capture_output=True)

    def test_an_unchanged_branch_passes(self) -> None:
        """A permanent veto is not a fix — this is the refutation partner.
        Mutation: make the recheck always exit non-zero -> red, and every
        narrowing close falls to the human prompt forever."""
        bullet, _ = self._armed_recheck()
        self.assertEqual(self._run(bullet).returncode, 0)

    def test_a_fix_touching_an_UNCOVERED_file_fails_and_says_why(self) -> None:
        """THE case. `src/db/**` is claimed by no surface, so the veto now
        withholds narrowing entirely and the frozen `pytest tests/cli` no
        longer covers the branch.

        Mutation: make the recheck always exit 0 -> red, and this auto-merges
        with a file no selected command tested.
        """
        bullet, repo = self._armed_recheck()
        self._commit(repo, "src/db/schema.py")
        result = self._run(bullet)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drift", result.stderr.lower())
        # Diagnosable in one read, or the feature gets switched off as flaky.
        self.assertIn("scope=", result.stderr)

    def test_a_fix_INSIDE_the_selected_surface_still_passes(self) -> None:
        """Precision, and why the digest covers the resolved COMMAND SET rather
        than the diff. A fix inside an already-selected surface changes what is
        tested by nothing, so it must not trip the gate.

        Mutation: digest the changed-path list instead of the command set ->
        red, and every review fix falls to the human prompt.
        """
        bullet, repo = self._armed_recheck()
        self._commit(repo, "src/cli/extra.py")
        self.assertEqual(self._run(bullet).returncode, 0)

    def test_an_UNCOMMITTED_fix_is_seen_too(self) -> None:
        """`base...HEAD` sees commits only, but the gate's commands run against
        the working tree — so an uncommitted review fix is the same defect.
        Untracked counts: authoring a new test file is that case.

        Mutation: drop the `git status --porcelain` union -> red.
        """
        bullet, repo = self._armed_recheck()
        (repo / "src" / "db").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "db" / "schema.py").write_text("x")
        self.assertNotEqual(self._run(bullet).returncode, 0)


if __name__ == "__main__":
    unittest.main()
