#!/usr/bin/env python3
"""CLI for the session teammate configuration marker.

Thin entry point over markers.read_teammate_config / write_teammate_config
so SKILL.md steps can read/write the setting without inlining a
`python3 -c` markers bootstrap. Mirrors cadence_cli.py.

Usage:
    teammate_config_cli.py --smm-dir DIR read            # print canonical token
    teammate_config_cli.py --smm-dir DIR write sonnet    # set the config
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markers


def _token_from_config(config: dict) -> str:
    """Derive the canonical token from a {enabled, default_model} dict."""
    if not config.get("enabled"):
        return "off"
    model = config.get("default_model")
    if model in markers._VALID_TEAMMATE_MODELS:
        return model
    return "inherit"


def _cmd_read(args: argparse.Namespace) -> int:
    config = markers.read_teammate_config(Path(args.smm_dir))
    print(_token_from_config(config))
    return 0


def _cmd_write(args: argparse.Namespace) -> int:
    markers.write_teammate_config(Path(args.smm_dir), args.token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session teammate config CLI")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_read = sub.add_parser("read", help="Print the canonical token")
    p_read.set_defaults(func=_cmd_read)

    p_write = sub.add_parser("write", help="Set the teammate config")
    p_write.add_argument("token", choices=sorted(markers.VALID_TEAMMATE_TOKENS))
    p_write.set_defaults(func=_cmd_write)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
