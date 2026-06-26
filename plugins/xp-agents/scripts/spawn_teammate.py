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
        [--branch paulingalls/story-001-foo] \
        [--model sonnet] \
        [--plugin-dir /path/to/plugins/xp-agents]
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# `worktree` import is the side-effect bootstrap that adds smm/ to
# sys.path (mirrors scripts/_common.py); pinned first via `isort: split`
# so the `sprint_store` import below resolves.
import worktree  # isort: split

import identity
import sprint_store


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


def build_command(
    name: str, model: str | None = None, plugin_dir: str | None = None
) -> list[str]:
    """Construct the claude -p command for a teammate.

    Prompt is piped via stdin, not passed as a CLI flag. When *model* is
    given, a --model flag selects the teammate's tier (e.g. sonnet for a
    delegated solo teammate); otherwise the claude -p default is inherited.

    When *plugin_dir* is given, a --plugin-dir flag loads that plugin into the
    headless teammate session. This is REQUIRED for the teammate to get the
    xp-agents skills, agents, and hooks: a worktree `claude -p` session does
    not apply the project-scoped marketplace enablement, so without
    --plugin-dir the plugin (and its full hook lifecycle) never loads.
    """
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
        "--include-partial-messages",
        "--verbose",
    ]
    if model is not None:
        cmd += ["--model", model]
    if plugin_dir is not None:
        cmd += ["--plugin-dir", plugin_dir]
    return cmd


def write_story_assignment(smm_dir: Path, name: str, story_id: str | None) -> None:
    """Write story assignment file for commit attribution. No-op if story_id is None."""
    if story_id is None:
        return
    worktree.write_story_assignment(smm_dir, name, story_id)


_DEFAULT_LOG_DIR = Path("/tmp")

# Watchdog: max silence (no .ping()) before SIGTERM. 900s = 15 min,
# sized to clear the longest legitimate thinking-on-large-context gap
# observed historically (~10 min on 256K-token inputs). Hard-coded;
# the next retro recalibrates if 900s false-positives or proves slow.
_WATCHDOG_TIMEOUT_S = 900
_WATCHDOG_POLL_INTERVAL_S = 5
# Grace period between SIGTERM and SIGKILL — SIGTERM may be ignored
# while the child is blocked in a C-level recv() on the API socket
# (the suspected hang mode); SIGKILL guarantees recovery fires.
_WATCHDOG_KILL_GRACE_S = 10


class _ActivityWatchdog:
    """Terminates *proc* when no .ping() arrives for *timeout_s* seconds.

    The run_with_tee main loop calls .ping() on each line read from the
    subprocess. If pings stop (because the spawned ``claude -p`` has
    gone silent), the watchdog calls ``proc.terminate()``, waits up to
    ``_WATCHDOG_KILL_GRACE_S`` for it to exit, then escalates to
    ``proc.kill()``. The main loop then sees stdout EOF, ``proc.wait()``
    returns a non-zero rc, and ``run_with_tee`` raises
    ``CalledProcessError`` as it does on any non-zero exit. The
    existing rc!=0 recovery path in main() takes over (story stays
    in-progress, prompt file preserved for re-spawn).

    *timeout_s*, *poll_interval_s*, and *kill_grace_s* default to
    ``None`` and resolve to the module constants at call time. Tests
    patch the constants; production callers omit all three args.
    """

    def __init__(
        self,
        proc,
        name: str,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
        kill_grace_s: float | None = None,
    ):
        self._proc = proc
        self._name = name
        self._timeout = _WATCHDOG_TIMEOUT_S if timeout_s is None else timeout_s
        self._poll = (
            _WATCHDOG_POLL_INTERVAL_S if poll_interval_s is None else poll_interval_s
        )
        self._kill_grace = (
            _WATCHDOG_KILL_GRACE_S if kill_grace_s is None else kill_grace_s
        )
        self._last_activity = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"watchdog-{name}"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Bound test-process thread accumulation; daemon=True still keeps
        # production exits clean if join misses.
        self._thread.join(timeout=self._poll + 0.1)

    def ping(self) -> None:
        # Single attribute write — atomic under the GIL; no lock needed.
        # Worst case is one extra poll cycle before termination.
        self._last_activity = time.monotonic()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            if time.monotonic() - self._last_activity > self._timeout:
                sys.stderr.write(
                    f"WATCHDOG: {self._name} silent >{self._timeout}s — terminating\n"
                )
                try:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=self._kill_grace)
                    except subprocess.TimeoutExpired:
                        sys.stderr.write(
                            f"WATCHDOG: {self._name} did not exit on SIGTERM "
                            f"within {self._kill_grace}s — SIGKILL\n"
                        )
                        self._proc.kill()
                except (OSError, subprocess.SubprocessError):
                    # Expected failure modes: process already exited
                    # (terminate/kill OSError), or wait raises a
                    # SubprocessError. Don't catch broader exceptions —
                    # an AttributeError from a bogus proc must crash
                    # visibly in tests rather than silently leak.
                    pass
                return


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

    The on-disk log preserves output up to the termination point so a
    stuck teammate can be inspected forensically. If the log file
    can't be opened, the spawn proceeds without teeing — investigation
    aid is best-effort, not load-bearing.

    Re-spawns of the same teammate name *append* with a session header so
    the forensic record from a prior hang survives a kill + retry.

    A liveness watchdog runs in a daemon thread alongside this loop:
    each line read pings it; if pings stop for ``_WATCHDOG_TIMEOUT_S``
    seconds, the watchdog terminates the subprocess (SIGTERM, then
    SIGKILL after a grace period). The main loop then sees stdout
    EOF, ``proc.wait()`` returns the signal exit code, and this
    function raises ``CalledProcessError`` — same recovery shape as
    any other non-zero exit. Without the watchdog, a child blocked
    indefinitely inside an HTTPS POST to the model API could keep
    the orchestrator waiting forever.

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
    watchdog = _ActivityWatchdog(proc, name)
    watchdog.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            watchdog.ping()
            sys.stdout.write(line)
            sys.stdout.flush()
            if log_file is not None:
                log_file.write(line)
                log_file.flush()
    finally:
        watchdog.stop()
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
    parser.add_argument("--model", default=None)
    parser.add_argument("--plugin-dir", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Parse args and spawn the teammate."""
    args = parse_args(argv)
    name = args.name

    cwd = os.getcwd()
    wt_path = create_worktree(name, cwd, branch=args.branch)
    cmd = build_command(name, args.model, args.plugin_dir)

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
        Path(args.prompt_file).unlink(missing_ok=True)
    finally:
        if combined_path is not None:
            Path(combined_path).unlink(missing_ok=True)

    # rc=0 path: mechanical promote to reviewing under close-then-done.
    # On rc!=0 the run_with_tee call above raised CalledProcessError,
    # this code never runs, the story stays in-progress for debug, and
    # args.prompt_file is preserved so the orchestrator can re-spawn
    # without reconstructing the prompt.
    # The CAS guard inside update_story_status_if rejects the promote
    # when the story has already been advanced past in-progress (e.g. an
    # orchestrator flipped it to done mid-run) — closing the TOCTOU
    # window the prior get_story → update_story_status pair exposed.
    if args.story_id is not None:
        sprint_store.update_story_status_if(
            Path(args.smm_dir),
            args.story_id,
            expected="in-progress",
            new="reviewing",
        )


if __name__ == "__main__":
    main()
