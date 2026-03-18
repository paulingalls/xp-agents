#!/bin/bash
set -euo pipefail
# Preload for xp-goal-collection: check if goals exist.
# Supports both four-pillar SMM (## Intent) and pre-curation format (## Project Goals).
# Uses anchored patterns (^## X$) to prevent substring collisions.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
if [ -f "$SMM_FILE" ] && grep -q "^## Intent$" "$SMM_FILE" 2>/dev/null; then
    echo "### Goals: PRESENT"
    grep -A 50 "^## Intent$" "$SMM_FILE" | sed '/^## [^I]/,$d' | head -20
elif [ -f "$SMM_FILE" ] && grep -q "^## Project Goals$" "$SMM_FILE" 2>/dev/null; then
    echo "### Goals: PRESENT"
    grep -A 50 "^## Project Goals$" "$SMM_FILE" | sed '/^## [^P]/,$d' | head -20
else
    echo "### Goals: NONE RECORDED"
    echo "**First-run: Must collect goals from the user.**"
fi
