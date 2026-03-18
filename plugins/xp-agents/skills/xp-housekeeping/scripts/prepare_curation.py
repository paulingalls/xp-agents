#!/usr/bin/env python3
"""Preload script for housekeeping: output curation data as JSON.

Calls prepare_curation_data() from materialize.py and prints the
structured JSON that housekeeping uses for four-pillar curation.

Usage:
    python3 prepare_curation.py [--smm-dir DIR]
"""

import json
import sys
from pathlib import Path

# Add smm/ to path so we can import materialize
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import materialize  # noqa: E402


def main() -> None:
    smm_dir: Path | None = None
    if len(sys.argv) > 2 and sys.argv[1] == "--smm-dir":
        smm_dir = Path(sys.argv[2])

    if smm_dir is None:
        from _append_impl import resolve_smm_dir

        smm_dir = resolve_smm_dir()

    data = materialize.prepare_curation_data(smm_dir)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
