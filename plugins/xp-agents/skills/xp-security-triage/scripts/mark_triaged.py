#!/usr/bin/env python3
"""Write .security-triaged marker for the commit gate."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

import _common
import markers
import security

parser = argparse.ArgumentParser(description="Write security triage marker")
parser.add_argument(
    "--smm-dir",
    type=Path,
    help="SMM directory (auto-resolved if omitted)",
)
args = parser.parse_args()

smm_dir = args.smm_dir if args.smm_dir else _common.resolve_smm_dir()
smm_dir = _common.try_validate_smm_dir(smm_dir)
if smm_dir is None:
    print("SMM not initialized.")
    sys.exit(0)

if security.security_triaged_exists(smm_dir):
    print("Security triage marker already exists.")
else:
    security.write_security_triaged(smm_dir)
    # Set review cycle flag for commit gate
    markers.set_review_flag(smm_dir, "main", "security_review_done")
    # Record triage in the event log so the retro can see it happened
    event = _common.make_event(
        _common.STATUS,
        "xp-security-triage",
        "Security triage complete — changes classified as non-security-relevant",
        working_on=[],
    )
    _common.append_safe(smm_dir, event)
    print("Security triage marker written. Commit gate cleared.")
