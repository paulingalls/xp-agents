#!/usr/bin/env python3
"""Persist a session_summary draft into session_history.json.

Reads the JSON dict produced by draft_summary.run() from stdin, appends
a new entry to session_history.json (story-001's ring-buffer module),
then prunes carry_forward items whose references are already resolved
in events.jsonl.

Single CLI front-end for SKILL.md Step 4 — keeps the skill body short
and the persistence logic unit-testable.
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import session_history  # noqa: E402
from _append_impl import now_iso  # noqa: E402

_REQUIRED_DRAFT_KEYS = ("summary", "carry_forward")


def run(smm_dir: Path, draft: dict) -> int:
    """Persist *draft* and prune now-resolved carry_forward. Returns count pruned.

    Missing required keys raise KeyError — draft_summary.run() guarantees
    them, and silently filling defaults would hide a producer regression.
    """
    missing = [k for k in _REQUIRED_DRAFT_KEYS if k not in draft]
    if missing:
        raise KeyError(f"draft missing required keys: {', '.join(missing)}")
    entry = {
        "ts": now_iso(),
        "summary": draft["summary"],
        "carry_forward": draft["carry_forward"],
    }
    session_history.append_entry(smm_dir, entry)
    _, resolutions = _common.load_events_with_resolutions(smm_dir)
    return session_history.prune_resolved(smm_dir, resolutions)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persist a draft_summary payload into session_history.json."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    raw = sys.stdin.read()
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        return 1
    if not isinstance(draft, dict):
        print("Stdin JSON must be an object", file=sys.stderr)
        return 1

    run(args.smm_dir, draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
