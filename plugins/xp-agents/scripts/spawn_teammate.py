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
    worktree.write_story_assignment(smm_dir, name, story_id)


_DEFAULT_LOG_DIR = Path("/tmp")


def run_with_tee(
    cmd: list[str],
    cwd: str,
    env: dict,
    stdin,
    name: str,
    log_dir: Path = _DEFAULT_LOG_DIR,
) -> None:
    """Run *cmd*, mirroring stdout (and merged stderr) to both this process'
    stdout and ``<log_dir>/<name>.log``. Caller passes an already-prefixed
    teammate name (e.g. ``teammate-astro``) so the log file lands at
    ``<log_dir>/teammate-astro.log``.

    The on-disk log preserves output up to a hang point so a stuck teammate
    can be inspected forensically. Note: while the teammate is producing no
    output (the hang case), the log will not grow — ``tail -f`` shows prior
    state, not live progress. If the log file can't be opened, the spawn
    proceeds without teeing — investigation aid is best-effort, not
    load-bearing.

    Raises ``subprocess.CalledProcessError`` on non-zero exit so callers
    keep the prior ``check=True`` failure semantics.
    """
    log_path = log_dir / f"{name}.log"
    log_file = None
    try:
        log_file = log_path.open("w")
    except OSError as exc:
        sys.stderr.write(
            f"WARN: tee log {log_path} unavailable ({exc}); spawning without tee\n"
        )

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if log_file is not None:
                log_file.write(line)
                log_file.flush()
    finally:
        if log_file is not None:
            log_file.close()
        proc.wait()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def ensure_teammate_prefix(name: str) -> str:
    """Auto-prefix teammate- if not already present."""
    if name.startswith(identity._TEAMMATE_PREFIX):
        return name
    return identity._TEAMMATE_PREFIX + name


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
    name = ensure_teammate_prefix(args.name)

    cwd = os.getcwd()
    wt_path = create_worktree(name, cwd)
    cmd = build_command(name)

    write_story_assignment(Path(args.smm_dir), name, args.story_id)

    env = os.environ.copy()
    env["SMM_DIR"] = args.smm_dir
    env[identity._XP_TEAMMATE_ENV] = name

    try:
        with open(args.prompt_file) as prompt_stdin:
            run_with_tee(cmd, cwd=wt_path, env=env, stdin=prompt_stdin, name=name)
    finally:
        Path(args.prompt_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
