#!/bin/bash
set -euo pipefail
# Preload for security triage: write diff to file, output path.
# Running the skill IS the triage — the agent reads the diff file and decides
# if /security-review is also needed. The marker is written unconditionally
# because the skill loading means triage happened.

# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Write diff to file instead of stdout
DIFF_FILE="${SMM_DIR}/.security-triage-diff.txt"
dump_diff full > "$DIFF_FILE" 2>/dev/null || true
echo "DIFF_FILE=${DIFF_FILE}"

# Write triage marker + log event (merged from mark_triaged.py)
python3 "${PLUGIN_ROOT}/skills/xp-security-triage/scripts/mark_triaged.py" --smm-dir "${SMM_DIR}" 2>/dev/null || true
