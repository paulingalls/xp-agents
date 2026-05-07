#!/usr/bin/env python3
"""Spawn a CLI teammate in a git worktree.

Creates a git worktree and launches an independent claude -p process.
The teammate inherits $SMM_DIR so its hooks write to the lead's SMM.
Called by /xp-assign via Bash with run_in_background.

Usage:
    python3 spawn_teammate.py \
        --name worktree-story-001 \
        --smm-dir /path/to/smm \
        --prompt-file /tmp/prompt.txt \
        [--story-id story-001] \
        [--branch paulingalls/story-001-foo]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import identity
import sprint_store
import worktree


def cleanup_existing(name: str, cwd: str) -> None:
    """Remove existing worktree and branch if present."""
    worktree.remove_worktree(name, cwd, force_branch=True)


def create_worktree(name: str, cwd: str, *, branch: str | None = None) -> str:
    """Create a git worktree for a teammate. Returns worktree path.

    When branch is provided, checks out that existing branch in the
    worktree instead of creating a new branch. Used by /xp-assign
    to place teammates on story branches.
    """
    cleanup_existing(name, cwd)

    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)

    if branch is not None:
        cmd = ["git", "worktree", "add", wt_path, branch]
    else:
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
    stdout and ``<log_dir>/<name>.log``. Caller passes the worktree name
    (e.g. ``worktree-story-001``) so the log file lands at
    ``<log_dir>/worktree-story-001.log``.

    The on-disk log preserves output up to a hang point so a stuck teammate
    can be inspected forensically. Note: while the teammate is producing no
    output (the hang case), the log will not grow — ``tail -f`` shows prior
    state, not live progress. If the log file can't be opened, the spawn
    proceeds without teeing — investigation aid is best-effort, not
    load-bearing.

    Re-spawns of the same teammate name *append* with a session header so
    the forensic record from a prior hang survives a kill + retry.

    Raises ``subprocess.CalledProcessError`` on non-zero exit so callers
    keep the prior ``check=True`` failure semantics.
    """
    log_path = log_dir / f"{name}.log"
    log_file = None
    try:
        log_file = log_path.open("a")
        log_file.write(
            f"\n===== spawn {name} {datetime.now(timezone.utc).isoformat()} =====\n"
        )
        log_file.flush()
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


def _worktree_preamble(wt_path: str) -> str:
    """Return the worktree-context preamble injected before the teammate prompt.

    Names the worktree path explicitly and the main-repo path derived from
    it, then instructs the teammate to re-root any absolute path under the
    main repo to the worktree. The preamble lands FIRST in the teammate's
    stdin so its rule is established before the prompt body's potentially
    misleading paths.

    Worktree layout (standardized by worktree.worktree_path):
    `<main_repo>/.claude/worktrees/<name>`.
    """
    main_repo = str(Path(wt_path).parent.parent.parent)
    return (
        "## Worktree Context (injected by spawn_teammate.py)\n"
        "\n"
        f"Your current working directory is the worktree at: `{wt_path}`\n"
        f"The main repository checkout is at:               `{main_repo}`\n"
        "\n"
        "All file paths in the prompt body that follows are intended to be "
        "RELATIVE to this worktree, even when they appear written as absolute "
        f"paths starting with `{main_repo}/`. Re-root any such absolute path "
        "to your worktree before reading or editing files. "
        f"Example: `{main_repo}/some/sub/path.py` becomes "
        f"`{wt_path}/some/sub/path.py`.\n"
        "\n"
        "The SMM directory (passed via $SMM_DIR) is intentionally OUTSIDE the "
        "worktree — use it unmodified.\n"
        "\n"
        "---\n"
        "\n"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Spawn a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--story-id", default=None)
    parser.add_argument("--branch", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Parse args and spawn the teammate."""
    args = parse_args(argv)
    name = args.name

    cwd = os.getcwd()
    wt_path = create_worktree(name, cwd, branch=args.branch)
    cmd = build_command(name)

    write_story_assignment(Path(args.smm_dir), name, args.story_id)

    env = os.environ.copy()
    env["SMM_DIR"] = args.smm_dir
    env[identity._XP_TEAMMATE_ENV] = name

    combined_path: str | None = None
    try:
        combined = _worktree_preamble(wt_path) + Path(args.prompt_file).read_text()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".prompt.txt", delete=False
        ) as tf:
            tf.write(combined)
            combined_path = tf.name
        with open(combined_path) as combined_stdin:
            run_with_tee(cmd, cwd=wt_path, env=env, stdin=combined_stdin, name=name)
    finally:
        Path(args.prompt_file).unlink(missing_ok=True)
        if combined_path is not None:
            Path(combined_path).unlink(missing_ok=True)

    # rc=0 path: mechanical promote to reviewing under close-then-done.
    # On rc!=0 the run_with_tee call above raised CalledProcessError,
    # this code never runs, and the story stays in-progress for debug.
    # Guard: only promote from in-progress — a story already done or
    # deferred (e.g. user manually advanced it mid-run) must not be
    # silently demoted back to reviewing.
    if args.story_id is not None:
        smm_dir = Path(args.smm_dir)
        if sprint_store.get_story(smm_dir, args.story_id)["status"] == "in-progress":
            sprint_store.update_story_status(smm_dir, args.story_id, "reviewing")


if __name__ == "__main__":
    main()
