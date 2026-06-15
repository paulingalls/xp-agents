#!/usr/bin/env python3
"""CLI for the session review cadence marker ('commit' | 'story').

Thin entry point over markers.read_review_cadence / write_review_cadence
so SKILL.md (WRITE) and the preload shell helper (READ) stop inlining a
`python3 -c` markers bootstrap. Mirrors branching.py/retro_cli.py: a
dedicated CLI that encapsulates the marker layout.

Usage:
    cadence_cli.py --smm-dir DIR read            # print 'commit' | 'story'
    cadence_cli.py --smm-dir DIR write story     # set the cadence
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markers


def _cmd_read(args: argparse.Namespace) -> int:
    print(markers.read_review_cadence(Path(args.smm_dir)))
    return 0


def _cmd_write(args: argparse.Namespace) -> int:
    markers.write_review_cadence(Path(args.smm_dir), args.cadence)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session review cadence CLI")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_read = sub.add_parser("read", help="Print the cadence ('commit' | 'story')")
    p_read.set_defaults(func=_cmd_read)

    p_write = sub.add_parser("write", help="Set the cadence")
    p_write.add_argument("cadence", choices=sorted(markers.VALID_CADENCES))
    p_write.set_defaults(func=_cmd_write)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
