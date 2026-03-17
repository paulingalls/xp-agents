#!/usr/bin/env python3
"""Write security review tracker for current HEAD."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

import _common

smm_dir = _common.resolve_smm_dir()
smm_dir = _common.try_validate_smm_dir(smm_dir)
if smm_dir is None:
    print("SMM not initialized.")
    sys.exit(0)

head_hash = _common.get_head_hash(".")
if head_hash is None:
    print("Could not determine HEAD hash.")
    sys.exit(0)

if _common.security_tracker_exists(smm_dir, head_hash):
    print(f"Security review already cleared for HEAD {head_hash[:8]}.")
else:
    _common.write_security_tracker(smm_dir, head_hash)
    print(f"Security review cleared for HEAD {head_hash[:8]}.")
