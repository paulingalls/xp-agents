#!/usr/bin/env python3
"""Pins: the spawn path fails LOUD instead of silently inheriting (story-010).

Defects on the spawn path, all silent:

1. An empty or whitespace-only tier flag reached `build_command` as a truthy
   `str` (only `is not None` was checked), so `--model ""` forwarded an empty
   flag and `--effort ""` produced a misleading "does not support effort ''"
   note. A shell that expands an unset var to `""` — the normal shape of an
   untiered spawn — is the caller that hits this.
2. With no model resolved the teammate silently ran at whatever tier the
   orchestrator happened to be on. The silence WAS the defect: an inherited
   tier must be observable, so the operator can tell "deliberately untiered"
   from "the tier var was empty".
3. The assign preload deleted a LIVE gate marker as its last act, so reading
   what it emits disarmed the plan-review gate. Non-mutating is now the
   default and the consume is opted into, because the accident happened
   exactly twice — both times on the unmarked path.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

# Imported for its side effect as well as its symbols: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible
# (see test_no_test_can_spawn_a_real_agent.py). This module drives
# spawn_teammate.main(), whose tail is the real spawn.
import conftest  # noqa: F401
import marker_names
import spawn_command
from conftest import _PLUGIN_ROOT, _IntegrationTestCase

_ASSIGN_SKILL = _PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md"
_ASSIGN_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"

# The opt-in the real assign invocation passes. Named here once so the prose pin
# and the behavioral pins cannot drift onto two different spellings.
_CONSUME_FLAG = "--consume-gate"


def _build(**kwargs) -> tuple[list[str], str]:
    """(argv, stderr) from build_command — the unit under test for the flag
    guard. Mirrors test_spawn_teammate_effort._capture_spawn's stderr capture
    without paying for the worktree/run_with_tee patching: the normalization
    lives in build_command, so main() only needs the one end-to-end pin below.
    """
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        cmd = spawn_command.build_command("worktree-story-010", **kwargs)
    return cmd, stderr.getvalue()


class TestEmptyTierFlagIsAbsent(unittest.TestCase):
    """An empty value means "not set", not "set to empty" (AC1)."""

    def test_empty_model_omits_the_flag(self):
        cmd, _ = _build(model="")
        self.assertNotIn("--model", cmd)

    def test_whitespace_model_omits_the_flag(self):
        cmd, _ = _build(model="   ")
        self.assertNotIn("--model", cmd)

    def test_real_model_is_still_forwarded(self):
        cmd, _ = _build(model="sonnet")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def test_model_is_stripped_before_forwarding(self):
        """A shell that interpolates a padded var must not hand argparse a
        value the tier table cannot match."""
        cmd, _ = _build(model=" sonnet ")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def test_empty_effort_omits_the_flag_without_an_unsupported_note(self):
        """`--effort ""` used to reach tier_wire.effort_supported and print
        "model does not support effort ''" — a note about a level nobody asked
        for, which reads as a real tier problem."""
        cmd, err = _build(model="opus", effort="")
        self.assertNotIn("--effort", cmd)
        self.assertNotIn("does not support", err)

    def test_whitespace_effort_omits_the_flag_without_an_unsupported_note(self):
        cmd, err = _build(model="opus", effort="  ")
        self.assertNotIn("--effort", cmd)
        self.assertNotIn("does not support", err)

    def test_empty_effort_with_no_model_says_nothing_about_effort(self):
        """The unverifiable-effort note is also wrong when no effort was asked
        for — the only note due here is the inherited-tier one."""
        _, err = _build(model="", effort="")
        self.assertNotIn("effort", err)

    def test_real_effort_still_forwarded_on_a_supporting_model(self):
        cmd, _ = _build(model="opus", effort="xhigh")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")

    def test_effort_is_stripped_before_the_support_check(self):
        cmd, _ = _build(model="opus", effort=" xhigh ")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")


class TestInheritedTierIsLoud(unittest.TestCase):
    """No model resolved → say so on stderr (AC2)."""

    def test_absent_model_notes_the_inherited_unverified_tier(self):
        _, err = _build()
        self.assertIn("inherited", err)
        self.assertIn("orchestrator", err)
        self.assertIn("unverified", err)

    def test_empty_model_notes_the_inherited_unverified_tier(self):
        """The empty-string path is the one an untiered shell spawn takes, so it
        must reach the SAME note as an omitted flag — not stay silent because
        `"" is not None`."""
        _, err = _build(model="")
        self.assertIn("inherited", err)
        self.assertIn("unverified", err)

    def test_resolved_model_notes_nothing(self):
        _, err = _build(model="sonnet")
        self.assertEqual(err, "")

    def test_note_reaches_stderr_through_a_real_spawn(self):
        """End-to-end through main(): the operator watching a live spawn is who
        the note is for, and stdout is the teammate's stream — it must not land
        there."""
        import spawn_teammate

        captured: dict[str, list[str]] = {}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        stderr, stdout = io.StringIO(), io.StringIO()
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(
                    spawn_teammate,
                    "run_with_tee",
                    side_effect=lambda cmd, *a, **k: captured.__setitem__("v", cmd),
                ),
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(stdout),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-010",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                        "--model",
                        "",
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        self.assertNotIn("--model", captured["v"])
        self.assertIn("inherited", stderr.getvalue())
        self.assertNotIn("inherited", stdout.getvalue())


class TestAssignPreloadIsNonDestructiveByDefault(_IntegrationTestCase):
    """Inspecting the preload must not disarm a gate (AC4).

    The marker is a live gate read by the lead's write gate and re-armed by the
    plan-review SubagentStop hook. Its old `rm -f` ran unconditionally as the
    preload's last line, so anyone running the preload to see what it emits
    cleared the gate — which happened twice while this story was being planned.

    An `--inspect` flag would reproduce the accident: the inspector is exactly
    the caller who does not know to pass a flag. So the safe path is the DEFAULT
    and the real invocation opts in.
    """

    def _marker(self) -> Path:
        return self.smm_dir / marker_names.ASSIGN_PENDING

    def _arm(self) -> Path:
        path = self._marker()
        path.write_text("sprint-001 story-001\n")
        return path

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return self._run_preload(_ASSIGN_PRELOAD, args=list(args))

    def test_bare_run_leaves_the_gate_marker(self):
        marker = self._arm()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            marker.is_file(),
            "running the preload for inspection deleted the live gate marker",
        )

    def test_bare_run_still_emits_the_decision_vars(self):
        """Non-mutating must not mean degraded: inspection is only useful if the
        emitted vars are the same ones the real invocation gets."""
        self._arm()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for var in ("SMM_DIR=", "TEAMMATE_DEFAULT=", "RECOMMENDED_TIER="):
            self.assertIn(var, result.stdout)

    def test_opt_in_consumes_the_marker(self):
        marker = self._arm()
        result = self._run(_CONSUME_FLAG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.is_file())

    def test_opt_in_consumes_exactly_once_and_a_second_run_is_clean(self):
        """ "Exactly once" has a second half: the consume must not error when the
        marker is already gone, or a re-invoked /xp-assign fails on the preload."""
        marker = self._arm()
        first = self._run(_CONSUME_FLAG)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertFalse(marker.is_file())
        second = self._run(_CONSUME_FLAG)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(marker.is_file())

    def test_opt_in_still_emits_the_decision_vars(self):
        self._arm()
        result = self._run(_CONSUME_FLAG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEAMMATE_DEFAULT=", result.stdout)


class TestAssignPreloadConsumeWiring(unittest.TestCase):
    """The static half: the real invocation opts in, via the marker helper."""

    def test_skill_invocation_passes_the_consume_flag(self):
        """The `!`-injected preload line IS the real assign invocation — if it
        does not opt in, the gate is never consumed and /xp-assign re-arms
        against itself forever."""
        body = _ASSIGN_SKILL.read_text(encoding="utf-8")
        injected = [
            line
            for line in body.splitlines()
            if line.startswith("!`") and "preload" in line
        ]
        self.assertTrue(injected, "no injected preload line in xp-assign/SKILL.md")
        self.assertTrue(
            any(_CONSUME_FLAG in line for line in injected),
            f"the injected preload line does not pass {_CONSUME_FLAG}:\n"
            + "\n".join(injected),
        )

    def test_preload_consumes_through_the_marker_helper(self):
        """`rm -f` on a marker path bypasses the marker convention (symlink
        refusal, one spelling of the filename). `consume_marker` already
        exists in the shared preload base."""
        preload = _ASSIGN_PRELOAD.read_text(encoding="utf-8")
        self.assertNotIn(marker_names.ASSIGN_PENDING, preload)
        self.assertIn("consume_marker ASSIGN_PENDING", preload)


if __name__ == "__main__":
    unittest.main()
