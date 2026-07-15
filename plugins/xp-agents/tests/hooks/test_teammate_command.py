#!/usr/bin/env python3
"""Tests for teammate_command.build_command — the `claude -p` command builder.

Split out of test_spawn_teammate.py alongside build_command itself (moved from
spawn_teammate.py to teammate_command.py under the 500-line cap). Covers the
flag shape: --name, allowed tools, output format, and the model / plugin-dir
gating.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class TestBuildCommand(unittest.TestCase):
    """build_command constructs correct claude -p arguments."""

    def test_basic_command_flags(self):
        """Command includes --name, --dangerously-skip-permissions, --output-format."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertIn("claude", cmd[0])
        self.assertIn("-p", cmd)
        self.assertIn("--name", cmd)
        idx = cmd.index("--name")
        self.assertEqual(cmd[idx + 1], "teammate-step-1")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--output-format", cmd)
        idx = cmd.index("--output-format")
        self.assertEqual(cmd[idx + 1], "stream-json")
        self.assertIn("--verbose", cmd)

    def test_includes_allowed_tools(self):
        """Command includes --allowedTools with expected tools."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertIn("--allowedTools", cmd)
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1]
        for tool in ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Skill"):
            self.assertIn(tool, tools)

    def test_omits_plugin_dir_when_not_provided(self):
        """No --plugin-dir when none is passed."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertNotIn("--plugin-dir", cmd)

    def test_includes_plugin_dir_when_provided(self):
        """--plugin-dir <path> is appended when given, so the headless
        teammate session loads the xp-agents plugin (and its skills, agents,
        and hooks). Without it the worktree session loads none of them —
        project-scoped marketplace enablement is not applied there."""
        import teammate_command

        cmd = teammate_command.build_command(
            name="teammate-step-1", plugin_dir="/plugins/xp-agents"
        )
        self.assertIn("--plugin-dir", cmd)
        idx = cmd.index("--plugin-dir")
        self.assertEqual(cmd[idx + 1], "/plugins/xp-agents")

    def test_no_input_file_flag(self):
        """Command does not include --input-file (prompt piped via stdin)."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertNotIn("--input-file", cmd)

    def test_includes_partial_messages_flag(self):
        """--include-partial-messages enables per-token streaming so the
        liveness watchdog sees mtime ticks during real model output;
        without it, only block-completion events fire (1-4 lines per
        message) and legitimate text/tool_use generation looks identical
        to a hang."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertIn("--include-partial-messages", cmd)

    def test_omits_model_flag_when_not_provided(self):
        """No --model flag when model is None — teammate inherits the
        claude -p default model."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1")
        self.assertNotIn("--model", cmd)

    def test_includes_model_flag_when_provided(self):
        """--model <name> is appended when a model is passed, so a delegated
        teammate can run on a chosen tier (e.g. sonnet)."""
        import teammate_command

        cmd = teammate_command.build_command(name="teammate-step-1", model="sonnet")
        self.assertIn("--model", cmd)
        idx = cmd.index("--model")
        self.assertEqual(cmd[idx + 1], "sonnet")


if __name__ == "__main__":
    unittest.main()
