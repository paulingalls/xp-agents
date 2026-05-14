#!/usr/bin/env python3
"""Render session_history.json as a ``### LAST_SESSION`` markdown block.

Front-end for session_history.py's read-side helpers. Promotes the
prior xp-kickoff-internal ``render_history.py`` to the canonical CLI
alongside ``smm_cli.py`` / ``retro_cli.py`` / etc. — session_history is
a general SMM artifact, not a kickoff-private one.

Usage:
    session_history_cli.py --smm-dir DIR render [--limit N]
    session_history_cli.py --smm-dir DIR validate

``render`` emits the markdown block to stdout; when ``events.jsonl``
contains ``session_end`` events, the most-recent entry's header is
annotated ``(stale — N sessions ended without /xp-end-session since
this summary)`` if intervening sessions ended without a summary. Empty
output on a missing history file (fresh install).

``validate`` runs the schema validator and exits non-zero with errors
on stderr; useful in CI / tooling that wants a loud failure mode.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import session_history

_DEFAULT_RENDER_LIMIT = 2


def _positive_int(value: str) -> int:
    """argparse type-validator: parse a positive int (>= 1)."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {parsed}")
    return parsed


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        data = session_history.load_history(args.smm_dir)
    except (ValueError, OSError) as exc:
        # Loud failure so corrupt / symlink-rejected history surfaces
        # instead of silently degrading to empty output. The xp-kickoff
        # preload wraps this call so it does not block session start.
        print(f"Error loading session_history: {exc}", file=sys.stderr)
        return 1

    entries = data.get("entries", [])
    if not entries:
        return 0

    rendered = session_history.render_markdown(
        entries[-args.limit :],
        session_end_timestamps=session_history.read_session_end_timestamps(
            args.smm_dir
        ),
    )
    if rendered:
        print(rendered, end="")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        session_history.load_history(args.smm_dir)
    except (ValueError, OSError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="session_history.json render / validate CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory (session_history.json lives here)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser(
        "render",
        help="Render the last N entries as a markdown LAST_SESSION block",
    )
    render.add_argument(
        "--limit",
        type=_positive_int,
        default=_DEFAULT_RENDER_LIMIT,
        help=f"Number of trailing entries to render (default {_DEFAULT_RENDER_LIMIT})",
    )

    sub.add_parser("validate", help="Validate session_history.json schema")

    args = parser.parse_args()
    dispatch = {"render": _cmd_render, "validate": _cmd_validate}
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
