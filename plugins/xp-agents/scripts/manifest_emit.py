#!/usr/bin/env python3
"""Derive the second harness's plugin manifest from the first's.

`.claude-plugin/plugin.json` is the hand-edited source of truth. This emitter
reads it and writes `.codex-plugin/plugin.json`; it NEVER writes the source.
Shared metadata (name, version, description) then holds by construction, and a
release bump edits one file.

The sharpest difference from `hooks_emit.py`: there, source and target are two
different FILENAMES in one directory, so "never writes the source" is
structural. Here they share the basename `plugin.json` and differ only by
DIRECTORY, so `--out-dir .claude-plugin` would overwrite the hand-edited
primary with generated content. `emit()` therefore raises when the resolved
target path equals the resolved source path — the hooks emitter's structural
safety does not carry over, so this guard is load-bearing rather than defensive.

Run with no arguments to regenerate in place:

    python3 plugins/xp-agents/scripts/manifest_emit.py
"""

import argparse
import json
from pathlib import Path

_MANIFEST_NAME = "plugin.json"


def default_source() -> Path:
    """The checked-in hand-edited manifest, resolved from this file."""
    return Path(__file__).parent.parent / ".claude-plugin" / _MANIFEST_NAME


def default_out_dir() -> Path:
    """The shipped second-harness manifest directory, resolved from this file."""
    return Path(__file__).parent.parent / ".codex-plugin"


def transform(source: dict) -> dict:
    """Return the second harness's manifest derived from the first's.

    Addition only, inverting the hooks emitter's subtraction: every key of the
    primary survives untouched, and exactly two keys are added.

    `skills` names the default directory itself, so it is safe under either
    merge rule (replace or add). `hooks` names the generated second-harness
    hooks variant explicitly — on that harness a component key REPLACES
    default directory discovery rather than merging, so omitting it would
    load the first harness's hooks file instead.
    """
    derived = json.loads(json.dumps(source))
    derived["skills"] = "./skills/"
    derived["hooks"] = "./hooks/hooks.codex.json"
    return derived


def emit(source: Path | None = None, out_dir: Path | None = None) -> Path:
    """Write the derived manifest into out_dir and return its path.

    Raises ValueError when the resolved target equals the resolved source,
    rather than overwriting the hand-edited primary with generated content.
    """
    source = source or default_source()
    out_dir = out_dir or default_out_dir()
    target = out_dir / _MANIFEST_NAME
    if target.resolve() == source.resolve():
        raise ValueError(f"refusing to overwrite the manifest source at {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
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
        help="output dir (default: shipped .codex-plugin/)",
    )
    args = parser.parse_args()
    print(emit(source=args.source, out_dir=args.out_dir))


if __name__ == "__main__":
    main()
