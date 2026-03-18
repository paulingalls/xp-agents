#!/usr/bin/env python3
"""Compact the SMM event log after housekeeping curation.

Called by housekeeping SKILL.md as the final step.
Uses curation-watermark-based retention policy.
"""

import argparse
import sys
from pathlib import Path

# Add smm/ to path for compact module
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

from compact import compact_after_curation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact event log after curation")
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    result = compact_after_curation(args.smm_dir)
    print(
        f"Compacted: {result['archived']} archived, "
        f"{result['retained']} retained ({result['smm_referenced']} SMM-referenced)"
    )


if __name__ == "__main__":
    main()
