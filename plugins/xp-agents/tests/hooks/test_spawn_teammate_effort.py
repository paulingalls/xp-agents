#!/usr/bin/env python3
"""Tests for spawn_teammate.py --effort forwarding + fail-safe guard (story-002).

--effort is forwarded to the claude -p command when the resolved model supports
the requested level (tier_wire.effort_supported), and dropped with a stderr note
when it does not — degrading to the model default rather than erroring the spawn.
When --model is omitted the resolved tier is unknown, so effort is dropped
(strict fail-safe). parse_args plumbing mirrors test_spawn_teammate_args.py;
the build_command flag-shape assertions reuse the main()->build_command capture
pattern from that file, extended here to also capture stderr for the drop path.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


def _capture_spawn(extra_args: list[str]) -> tuple[list[str], str]:
    """Run spawn_teammate.main with a throwaway prompt file and patched
    create_worktree/run_with_tee, returning the (claude -p argv, captured
    stderr) pair. Mirrors test_spawn_teammate_args._capture_spawn_argv, adding
    stderr capture so the fail-safe drop path's log line can be asserted."""
    import spawn_teammate

    captured: dict[str, list[str]] = {}

    def capture_run(cmd, *args, **kwargs):
        captured["value"] = cmd

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test prompt")
        prompt_path = f.name

    stderr = io.StringIO()
    try:
        with (
            patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
            patch.object(spawn_teammate, "run_with_tee", side_effect=capture_run),
            contextlib.redirect_stderr(stderr),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "worktree-story-002",
                    "--smm-dir",
                    "/tmp/smm",
                    "--prompt-file",
                    prompt_path,
                    *extra_args,
                ]
            )
    finally:
        Path(prompt_path).unlink(missing_ok=True)
    return captured["value"], stderr.getvalue()


class TestEffortArg(unittest.TestCase):
    """--effort CLI arg parsing."""

    def test_effort_arg_optional(self):
        """--effort defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.effort)

    def test_effort_arg_accepted(self):
        """--effort is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--effort",
                "xhigh",
            ]
        )
        self.assertEqual(args.effort, "xhigh")


class TestEffortForwarding(unittest.TestCase):
    """--effort forwarding + fail-safe guard through main()->build_command."""

    def test_forwarded_when_supported(self):
        """--model opus --effort xhigh → argv includes the effort flag (AC1)."""
        cmd, _ = _capture_spawn(["--model", "opus", "--effort", "xhigh"])
        self.assertIn("--effort", cmd)
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")

    def test_dropped_and_logged_when_unsupported(self):
        """--model haiku --effort high → flag dropped, stderr notes the
        unsupported pair, but the spawn still proceeds (AC2)."""
        cmd, err = _capture_spawn(["--model", "haiku", "--effort", "high"])
        self.assertNotIn("--effort", cmd)
        self.assertIn("haiku", err)
        self.assertIn("high", err)
        # spawn still proceeded — run_with_tee received the command.
        self.assertIn("claude", cmd)

    def test_no_effort_flag_when_absent(self):
        """No --effort → argv has no effort flag (AC3, unchanged behavior)."""
        cmd, _ = _capture_spawn(["--model", "opus"])
        self.assertNotIn("--effort", cmd)

    def test_dropped_when_model_inherited(self):
        """--effort with no --model → resolved tier unknown, strict fail-safe
        drops the flag and logs, spawn proceeds."""
        cmd, err = _capture_spawn(["--effort", "high"])
        self.assertNotIn("--effort", cmd)
        self.assertIn("high", err)
        self.assertIn("claude", cmd)


if __name__ == "__main__":
    unittest.main()
