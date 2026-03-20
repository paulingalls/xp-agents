#!/bin/bash
set -euo pipefail
# Preload for xp-goal-collection: show current goals from the Intent pillar.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
echo "### Current Goals"
if [ -f "$SMM_FILE" ] && smm_has_section "Intent"; then
    smm_section "Intent" | head -20
else
    echo "No goals recorded yet."
fi
