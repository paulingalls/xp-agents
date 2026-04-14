#!/usr/bin/env python3
"""Spawn a CLI teammate in a git worktree.

Creates a git worktree, detects plugin loading mode, and launches
an independent claude -p process. Called by /xp-assign via Bash
with run_in_background.

Usage:
    python3 spawn_teammate.py \
        --name teammate-step-1 \
        --smm-dir /path/to/smm \
        --prompt-file /tmp/prompt.txt
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import identity
import worktree


def cleanup_existing(name: str, cwd: str) -> None:
    """Remove existing worktree and branch if present."""
    worktree.remove_worktree(name, cwd, force_branch=True)


def create_worktree(name: str, cwd: str) -> str:
    """Create a git worktree for a teammate. Returns worktree path."""
    cleanup_existing(name, cwd)

    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)

    cmd = ["git", "worktree", "add", "-b", name, wt_path]
    current = identity.get_current_branch(cwd)
    if current:
        cmd.append(current)

    subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    return wt_path


def detect_plugin_mode() -> str | None:
    """Detect plugin loading mode from environment.

    Returns CLAUDE_PLUGIN_ROOT for inline (dev) mode, None for
    marketplace installs.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if "inline" in plugin_data:
        return os.environ.get("CLAUDE_PLUGIN_ROOT")
    return None


_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent"


def build_command(
    name: str,
    prompt_file: str,
    plugin_dir: str | None,
) -> list[str]:
    """Construct the claude -p command for a teammate."""
    cmd = [
        "claude",
        "-p",
        "--name",
        name,
        "--dangerously-skip-permissions",
        "--allowedTools",
        _ALLOWED_TOOLS,
        "--output-format",
        "stream-json",
        "--verbose",
        "--input-file",
        prompt_file,
    ]
    if plugin_dir:
        cmd.extend(["--plugin-dir", plugin_dir])
    return cmd


def main(argv: list[str] | None = None) -> None:
    """Parse args and spawn the teammate."""
    parser = argparse.ArgumentParser(description="Spawn a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--prompt-file", required=True)
    args = parser.parse_args(argv)

    cwd = os.getcwd()
    wt_path = create_worktree(args.name, cwd)
    plugin_dir = detect_plugin_mode()
    cmd = build_command(args.name, args.prompt_file, plugin_dir)

    env = os.environ.copy()
    env["SMM_DIR"] = args.smm_dir
    env["TEAMMATE_ID"] = args.name

    subprocess.run(cmd, cwd=wt_path, env=env, check=True)


if __name__ == "__main__":
    main()
