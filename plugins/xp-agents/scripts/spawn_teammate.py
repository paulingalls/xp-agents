#!/usr/bin/env python3
"""Spawn a CLI teammate in a git worktree.

Creates a git worktree and launches an independent claude -p process.
The teammate inherits $SMM_DIR so its hooks write to the lead's SMM.
Called by /xp-assign via Bash with run_in_background.

Usage:
    python3 spawn_teammate.py \
        --name teammate-step-1 \
        --smm-dir /path/to/smm \
        --prompt-file /tmp/prompt.txt \
        [--story-id story-001]
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


_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Grep,Glob,Skill,Agent"


def build_command(name: str) -> list[str]:
    """Construct the claude -p command for a teammate.

    Prompt is piped via stdin, not passed as a CLI flag.
    """
    return [
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
    ]


def write_story_assignment(smm_dir: Path, name: str, story_id: str | None) -> None:
    """Write story assignment file for commit attribution. No-op if story_id is None."""
    if story_id is None:
        return
    path = worktree.story_assignment_path(smm_dir, name)
    path.write_text(story_id, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Spawn a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--story-id", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Parse args and spawn the teammate."""
    args = parse_args(argv)

    cwd = os.getcwd()
    wt_path = create_worktree(args.name, cwd)
    cmd = build_command(args.name)

    write_story_assignment(Path(args.smm_dir), args.name, args.story_id)

    env = os.environ.copy()
    env["SMM_DIR"] = args.smm_dir

    with open(args.prompt_file) as prompt_stdin:
        subprocess.run(cmd, cwd=wt_path, env=env, stdin=prompt_stdin, check=True)


if __name__ == "__main__":
    main()
