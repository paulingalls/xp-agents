#!/bin/bash
set -euo pipefail
# Preload for security triage: output SMM_DIR, write triage marker.
# /security-review does its own diff — no need to preload one.
# XP values injected universally via SubagentStart.

# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Write triage marker + log event
python3 "${PLUGIN_ROOT}/skills/xp-security-triage/scripts/mark_triaged.py" --smm-dir "${SMM_DIR}" 2>/dev/null || true
