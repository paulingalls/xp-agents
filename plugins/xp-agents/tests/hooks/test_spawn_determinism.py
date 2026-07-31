#!/usr/bin/env python3
"""Pins: the spawn path fails LOUD instead of silently inheriting (story-010).

The flag-forwarding half. Both defects here are the same shape — a value that is
empty rather than absent — and both were silent:

1. An empty or whitespace-only tier flag reached `build_command` as a truthy
   `str` (only `is not None` was checked), so `--model ""` forwarded an empty
   flag and `--effort ""` produced a misleading "does not support effort ''"
   note. A shell that expands an unset var to `""` — the normal shape of an
   untiered spawn — is the caller that hits this. `--plugin-dir` carried the
   identical defect with a worse consequence: no skills, agents or hooks.
2. With no model resolved the teammate silently ran at whatever tier the
   orchestrator happened to be on. The silence WAS the defect: an inherited
   tier must be observable, so the operator can tell "deliberately untiered"
   from "the tier var was empty".

Split at 651 lines. The story's other three pins are their own suites, one per
contract: `test_assign_preload_gate.py` (the gate marker),
`test_domain_glob_collision.py` (glob-aware collision) and
`test_teammate_cadence_render.py` (the cadence render).
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

# Imported for its side effect as well as its symbols: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible
# (see test_no_test_can_spawn_a_real_agent.py). This module drives
# spawn_teammate.main(), whose tail is the real spawn.
import conftest  # noqa: F401
import spawn_command


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
        """A plugin dir is passed too: the note under test is the TIER one, and
        the plugin-less note would otherwise make this pass for the wrong
        reason."""
        _, err = _build(model="sonnet", plugin_dir="/p")
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


class TestPluginDirEmptyFlagIsAbsent(unittest.TestCase):
    """--plugin-dir carries the identical empty-flag defect --model had, and a
    worse consequence: an empty CLAUDE_PLUGIN_ROOT spawns a teammate with no
    skills, agents or hooks — every XP gate silently absent (adda51fd0778)."""

    def test_empty_plugin_dir_omits_the_flag(self):
        cmd = spawn_command.build_command("worktree-story-001", plugin_dir="")
        self.assertNotIn("--plugin-dir", cmd)

    def test_whitespace_plugin_dir_omits_the_flag(self):
        cmd = spawn_command.build_command("worktree-story-001", plugin_dir="   ")
        self.assertNotIn("--plugin-dir", cmd)

    def test_real_plugin_dir_is_forwarded_stripped(self):
        cmd = spawn_command.build_command("worktree-story-001", plugin_dir=" /p ")
        self.assertIn("--plugin-dir", cmd)
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/p")

    def test_absent_plugin_dir_is_announced(self):
        """Dropping the flag has the SAME consequence the empty flag had — an
        ungated teammate — so normalizing it silently only moves the failure.
        The inherited-tier note's argument applies with more force here."""
        _, err = _build(model="sonnet")
        self.assertIn("plugin", err.lower())
        self.assertIn("gate", err.lower())

    def test_whitespace_plugin_dir_does_not_defeat_the_env_fallback(self):
        """`args.plugin_dir or os.environ[...]` is a truthiness test, and
        `"   "` is truthy: without the shared emptiness test main() skips the
        CLAUDE_PLUGIN_ROOT fallback and build_command then drops the flag."""
        import spawn_teammate

        captured: dict[str, list[str]] = {}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name
        try:
            with (
                patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/env/xp-agents"}),
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(
                    spawn_teammate,
                    "run_with_tee",
                    side_effect=lambda cmd, *a, **k: captured.__setitem__("v", cmd),
                ),
                contextlib.redirect_stderr(io.StringIO()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        "worktree-story-010",
                        "--smm-dir",
                        "/tmp/smm",
                        "--prompt-file",
                        prompt_path,
                        "--plugin-dir",
                        "   ",
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        cmd = captured["v"]
        self.assertIn("--plugin-dir", cmd)
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/env/xp-agents")


if __name__ == "__main__":
    unittest.main()
