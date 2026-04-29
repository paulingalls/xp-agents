#!/usr/bin/env python3
"""One-shot reconciler for historical commit events' metadata.story_id.

Pre-Tier-0, _resolve_story_id fell back to file-domain overlap when no
teammate marker existed; ties returned None and partial overlaps could
attribute to the wrong story. v2.28.1 added a Tier-0 `[story-NNN]`
commit-message-prefix parser as authoritative ground truth for new
commits, but historical events keep the older (sometimes wrong, often
missing) story_id.

This script walks events.jsonl, finds commit events whose content
starts with `[story-NNN]`, and writes the prefix value into
metadata.story_id when it differs (or is absent). Default is dry-run;
``--apply`` performs the rewrite via tempfile + atomic rename.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import resolve_smm_dir, write_text_atomic
from story_metrics import STORY_PREFIX_RE


@dataclass
class Report:
    commits: int = 0
    with_prefix: int = 0
    changed: int = 0


def _events_file(smm_dir: Path) -> Path:
    return smm_dir / "events.jsonl"


def reconcile(smm_dir: Path, *, apply: bool) -> Report:
    """Walk events.jsonl, fix story_id on commits with a [story-NNN] prefix.

    Dry-run reports counts without touching the file. ``apply=True``
    rewrites events.jsonl atomically via a tempfile + rename.
    """
    path = _events_file(smm_dir)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    report = Report()
    for line in raw_lines:
        if not line.strip():
            out_lines.append(line)
            continue
        event = json.loads(line)
        if event.get("type") != "commit":
            out_lines.append(line)
            continue
        report.commits += 1
        content = event.get("content", "")
        match = STORY_PREFIX_RE.match(content) if isinstance(content, str) else None
        if match is None:
            out_lines.append(line)
            continue
        report.with_prefix += 1
        prefix_id = match.group(1)
        metadata = event.get("metadata") or {}
        if metadata.get("story_id") == prefix_id:
            out_lines.append(line)
            continue
        report.changed += 1
        metadata["story_id"] = prefix_id
        event["metadata"] = metadata
        out_lines.append(json.dumps(event))

    if apply and report.changed:
        write_text_atomic(path, "\n".join(out_lines) + "\n")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill commit story_id from prefix")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        help="Override SMM directory (default: auto-detect from git)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite events.jsonl. Without this flag, only report.",
    )
    args = parser.parse_args()
    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()
    if smm_dir is None:
        print("Error: Not in a git repository", file=sys.stderr)
        return 1
    report = reconcile(smm_dir, apply=args.apply)
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] commits={report.commits} with_prefix={report.with_prefix} "
        f"changed={report.changed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
