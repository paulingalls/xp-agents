#!/usr/bin/env python3
"""Derive the second harness's hooks manifest from the first's.

`hooks/hooks.json` is the hand-edited source of truth. This emitter reads it
and writes `hooks/hooks.codex.json`; it NEVER writes the source. That direction
is the whole design: the first harness's manifest is byte-identical after a run
by construction, so the fourteen suites that read it need no change, and the
second variant cannot drift because a pin regenerates it and compares.

Why a script under `scripts/` rather than under `hooks/`: `tests/_pin_helpers.py`
scans `scripts/` and `smm/` for shipped Python and deliberately skips `hooks/`
("it holds hooks.json and no Python at all"). An emitter under `hooks/` would
escape the file-size and language-leak pins entirely.

Run with no arguments to regenerate in place:

    python3 plugins/xp-agents/scripts/hooks_emit.py
"""

import argparse
import json
from pathlib import Path

_VARIANT_NAME = "hooks.codex.json"
_SOURCE_NAME = "hooks.json"


def default_source() -> Path:
    """The checked-in source manifest, resolved from this file."""
    return Path(__file__).parent.parent / "hooks" / _SOURCE_NAME


def default_out_dir() -> Path:
    """The shipped hooks directory, resolved from this file."""
    return Path(__file__).parent.parent / "hooks"


def transform(source: dict) -> dict:
    """Return the second harness's manifest derived from the first's."""
    return json.loads(json.dumps(source))


def emit(source: Path | None = None, out_dir: Path | None = None) -> Path:
    """Write the derived variant into out_dir and return its path."""
    source = source or default_source()
    out_dir = out_dir or default_out_dir()
    data = json.loads(source.read_text(encoding="utf-8"))
    target = out_dir / _VARIANT_NAME
    target.write_text(json.dumps(transform(data), indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=None, help="source manifest (default: shipped)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output dir (default: shipped hooks/)",
    )
    args = parser.parse_args()
    print(emit(source=args.source, out_dir=args.out_dir))


if __name__ == "__main__":
    main()
