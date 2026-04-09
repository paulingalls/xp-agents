#!/usr/bin/env python3
"""Save curated SMM: parse JSON from stdin, validate, write atomically.

Accepts JSON on stdin, validates against smm_schema, writes
shared_mental_model.json atomically, updates the curation watermark
with the current event count, and compacts the event log.

Usage:
    echo '<json>' | python3 save_smm.py --smm-dir DIR
"""

import argparse
import contextlib
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import compact  # noqa: E402
import materialize  # noqa: E402
import smm_store  # noqa: E402


def run(content: str, smm_dir: Path) -> None:
    """Parse JSON, validate, write, update watermark, compact.

    Raises:
        json.JSONDecodeError: If content is not valid JSON.
        ValueError: If content fails SMM schema validation.
            Existing file on disk is left untouched.
    """
    data = json.loads(content)
    smm_store.save_smm(smm_dir, data)

    # Update curation watermark with current event count
    events, _ = materialize.parse_events(smm_dir)
    materialize.write_curation_watermark(smm_dir, len(events), "xp-housekeeping")

    # Compact the event log — failures never fail the write
    with contextlib.suppress(Exception):
        compact.compact_after_curation(smm_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save curated SMM JSON and update watermark"
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    args = parser.parse_args()

    content = sys.stdin.read()
    run(content, args.smm_dir)


if __name__ == "__main__":
    main()
