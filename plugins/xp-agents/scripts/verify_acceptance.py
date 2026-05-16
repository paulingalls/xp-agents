#!/usr/bin/env python3
"""Run a story's acceptance_execution commands in order.

Reads sprint.json from the SMM dir, finds the story by id, and runs every
command in `acceptance_execution` (back-compat: single `command: str` is
treated as a one-element list). Exits non-zero on the first command that
returns non-zero, naming the failing command on stderr. Exits 0 if all
commands pass.

Designed to give an honest, multi-command acceptance gate so a story
cannot "lie" about acceptance — e.g., pytest passing while a separate
grep in the AC goes unverified.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _acceptance_execution import extract_commands
from _append_impl import resolve_smm_dir
from sprint_store import get_story


def _run_commands(commands: list[str]) -> int:
    """Run each command in order; return 0 on all-green, else first non-zero exit."""
    multi = len(commands) > 1
    for i, cmd in enumerate(commands):
        # shell=True: AC commands are shell strings (pytest, grep, bash
        # one-liners with pipes/redirects). Stories declare them; the SMM
        # is trusted local state, not external input.
        result = subprocess.run(cmd, shell=True, check=False)
        if result.returncode != 0:
            label = f"commands[{i}]" if multi else "command"
            print(
                f"verify_acceptance: {label} failed (exit {result.returncode}): {cmd}",
                file=sys.stderr,
            )
            return result.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a story's acceptance_execution commands in order.",
    )
    parser.add_argument("--story", required=True, help="Story ID")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        default=None,
        help="SMM directory (defaults to $SMM_DIR / init.sh resolution)",
    )
    args = parser.parse_args()

    smm_dir = args.smm_dir or resolve_smm_dir()
    if smm_dir is None:
        print("verify_acceptance: could not resolve SMM directory", file=sys.stderr)
        return 1

    try:
        story = get_story(smm_dir, args.story)
    except (ValueError, OSError) as exc:
        print(f"verify_acceptance: {exc}", file=sys.stderr)
        return 1

    ae = story.get("acceptance_execution")
    if not ae:
        print(
            f"verify_acceptance: story {args.story!r} "
            "has no acceptance_execution block",
            file=sys.stderr,
        )
        return 1

    return _run_commands(extract_commands(ae))


if __name__ == "__main__":
    sys.exit(main())
