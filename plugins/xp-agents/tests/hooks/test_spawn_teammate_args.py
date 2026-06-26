#!/usr/bin/env python3
"""Tests for spawn_teammate.py CLI argument plumbing.

Covers parse_args for --story-id / --branch / --model / --plugin-dir and the
main()->build_command flow-through (including the --plugin-dir env self-resolve
from CLAUDE_PLUGIN_ROOT). build_command flag-shape, story-assignment, and
mechanical-promote tests live in test_spawn_teammate.py; prompt + stdout
pipeline tests in test_spawn_teammate_pipeline.py; liveness watchdog tests in
test_spawn_teammate_watchdog.py.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


def _capture_spawn_argv(extra_args: list[str]) -> list[str]:
    """Run spawn_teammate.main with a throwaway prompt file and patched
    create_worktree/run_with_tee, returning the claude -p argv that
    build_command produced. Shared by the --model / --plugin-dir flow-through
    tests so a change to main()'s patch surface lives in one place."""
    import spawn_teammate

    captured: dict[str, list[str]] = {}

    def capture_run(cmd, *args, **kwargs):
        captured["value"] = cmd

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test prompt")
        prompt_path = f.name

    try:
        with (
            patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
            patch.object(spawn_teammate, "run_with_tee", side_effect=capture_run),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "worktree-story-001",
                    "--smm-dir",
                    "/tmp/smm",
                    "--prompt-file",
                    prompt_path,
                    *extra_args,
                ]
            )
    finally:
        Path(prompt_path).unlink(missing_ok=True)
    return captured["value"]


class TestStoryIdArg(unittest.TestCase):
    """--story-id CLI arg for story attribution."""

    def test_story_id_optional(self):
        """--story-id defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.story_id)

    def test_story_id_accepted(self):
        """--story-id is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--story-id",
                "story-001",
            ]
        )
        self.assertEqual(args.story_id, "story-001")


class TestBranchArg(unittest.TestCase):
    """--branch CLI arg for story branch checkout."""

    def test_branch_arg_optional(self):
        """--branch defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.branch)

    def test_branch_arg_accepted(self):
        """--branch is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--branch",
                "paulingalls/story-001-schema-store",
            ]
        )
        self.assertEqual(args.branch, "paulingalls/story-001-schema-store")


class TestModelArg(unittest.TestCase):
    """--model CLI arg selects the teammate's claude -p model tier."""

    def test_model_arg_optional(self):
        """--model defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.model)

    def test_model_arg_accepted(self):
        """--model is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--model",
                "sonnet",
            ]
        )
        self.assertEqual(args.model, "sonnet")

    def test_model_flows_through_main_to_command(self):
        """--model passed to main() reaches the claude -p argv via build_command."""
        cmd = _capture_spawn_argv(["--model", "sonnet"])
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")


class TestPluginDirArg(unittest.TestCase):
    """--plugin-dir CLI arg loads the plugin into the teammate session."""

    def test_plugin_dir_optional(self):
        """--plugin-dir defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.plugin_dir)

    def test_plugin_dir_accepted(self):
        """--plugin-dir is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--plugin-dir",
                "/plugins/xp-agents",
            ]
        )
        self.assertEqual(args.plugin_dir, "/plugins/xp-agents")

    def test_plugin_dir_flows_through_main_to_command(self):
        """--plugin-dir passed to main() reaches the claude -p argv."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            cmd = _capture_spawn_argv(["--plugin-dir", "/plugins/xp-agents"])
        self.assertIn("--plugin-dir", cmd)
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/plugins/xp-agents")

    def test_plugin_dir_defaults_to_env_when_omitted(self):
        """When --plugin-dir is omitted, main() self-resolves it from
        CLAUDE_PLUGIN_ROOT so a caller that forgets the flag can't silently
        spawn an ungated (plugin-less) teammate."""
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/env/xp-agents"}):
            cmd = _capture_spawn_argv([])
        self.assertIn("--plugin-dir", cmd)
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/env/xp-agents")

    def test_explicit_plugin_dir_overrides_env(self):
        """An explicit --plugin-dir wins over CLAUDE_PLUGIN_ROOT."""
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/env/xp-agents"}):
            cmd = _capture_spawn_argv(["--plugin-dir", "/explicit/xp-agents"])
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/explicit/xp-agents")

    def test_omits_plugin_dir_when_neither_flag_nor_env(self):
        """No --plugin-dir in argv when neither the flag nor CLAUDE_PLUGIN_ROOT
        is present — bare invocations stay unchanged (no env coupling)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            cmd = _capture_spawn_argv([])
        self.assertNotIn("--plugin-dir", cmd)


if __name__ == "__main__":
    unittest.main()
