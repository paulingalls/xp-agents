#!/usr/bin/env python3
"""Write .security-triaged-<agent_id> marker for the commit gate."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "smm"))

import _common
import event_schema
import identity
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

# Agent-scoped marker: prevents concurrent teammate commits from consuming
# each other's triage flags. Scope is derived from the worktree path.
agent_id = identity.resolve_agent_id_from_cwd(os.getcwd())

if security.security_triaged_exists(smm_dir, agent_id):
    print("Security triage marker already exists.")
else:
    security.write_security_triaged(smm_dir, agent_id)
    # Set review cycle flag for commit gate
    markers.set_review_flag(smm_dir, agent_id, "security_review_done")
    # Record triage in the event log so the retro can see it happened.
    # Content is neutral — the agent decides next steps after seeing the diff.
    event = _common.make_event(
        _common.STATUS,
        "xp-security-triage",
        "Security triage started — reviewing staged changes",
        working_on=[],
        metadata={"action": event_schema.STATUS_ACTION_SECURITY_TRIAGE_STARTED},
    )
    _common.append_safe(smm_dir, event)
    print("Security triage marker written. Commit gate cleared.")
