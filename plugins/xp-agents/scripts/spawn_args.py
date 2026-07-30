#!/usr/bin/env python3
"""The spawn CLI surface: every flag spawn_teammate accepts, and what it means.

Extracted from spawn_teammate.py (which owns worktree/marker lifecycle, prompt
resolution, and the story promote) to keep both files under the size cap — the
fifth such leaf, beside spawn_command, spawn_prompt, teammate_runner and
worktree_bootstrap. Pure argparse: no I/O and no SMM/plugin imports, so it needs
no sys.path bootstrap (the same property spawn_prompt holds, for the same
reason).

spawn_teammate imports ``parse_args`` back, so ``spawn_teammate.parse_args`` IS
this function and every caller and test spelling resolves unchanged.
"""

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Spawn a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument(
        "--prompt-file",
        required=False,
        default=None,
        help=(
            "Path to the teammate prompt. OPTIONAL: when omitted or empty, "
            "spawn resolves the deterministic project_prompt_path(--smm-dir, "
            "--name) itself — the same path --print-prompt-path returns. This "
            "avoids threading a queried path across separate Bash tool calls "
            "(shell state does not persist), which handed spawn an empty value."
        ),
    )
    parser.add_argument(
        "--print-log-path",
        action="store_true",
        help=(
            "Print the deterministic project-scoped forensic-log path for "
            "--name and exit 0 WITHOUT spawning. /xp-assign calls this to "
            "surface the live `tail -f` target to the lead — the path matches "
            "run_with_tee's own log so a tailer watches the file the tee writes."
        ),
    )
    parser.add_argument(
        "--print-prompt-path",
        action="store_true",
        help=(
            "Print the deterministic project-scoped prompt-file path for --name "
            "(creating its parent dir) and exit 0 WITHOUT spawning. /xp-assign "
            "calls this so the orchestrator writes the teammate prompt to a "
            "per-project location instead of a flat /tmp/prompt-<id>.txt that "
            "collides across concurrent sessions."
        ),
    )
    parser.add_argument("--story-id", default=None)
    parser.add_argument("--branch", default=None)
    # --model / --effort: an empty or whitespace-only value means ABSENT, not
    # "set to empty" — build_command normalizes both and omits the flag. Callers
    # are shells interpolating a tier variable, and an unset variable arrives as
    # `""`; without the normalization that forwarded an empty flag. Absent
    # --model additionally makes build_command announce the inherited tier on
    # stderr, so an unset variable is never mistaken for a deliberate choice.
    parser.add_argument("--model", default=None)
    parser.add_argument("--plugin-dir", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=(
            "Run the teammate in the main checkout (solo delegation) instead of "
            "a worktree: skip create_worktree + the worktree preamble, run in the "
            "process cwd, and skip the rc=0 promote-to-reviewing (the story stays "
            "in-progress/solo for /xp-accept's solo path)."
        ),
    )
    return parser.parse_args(argv)
