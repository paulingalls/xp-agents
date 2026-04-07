#!/bin/bash
set -euo pipefail
# Preload for security triage: show diff + write marker + log event.
# Running the skill IS the triage — the agent sees the diff and decides
# if /security-review is also needed. The marker is written unconditionally
# because the skill loading means triage happened.

# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_values
echo ""

dump_diff full

# Write triage marker + log event (merged from mark_triaged.py)
python3 "${PLUGIN_ROOT}/skills/xp-security-triage/scripts/mark_triaged.py" --smm-dir "${SMM_DIR}" 2>/dev/null || true
