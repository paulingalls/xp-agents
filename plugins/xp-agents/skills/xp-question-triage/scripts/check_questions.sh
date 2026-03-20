#!/bin/bash
set -euo pipefail
# Preload for xp-question-triage: check for open questions and intents.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"

# Open questions live in the Risks pillar
if [ -f "$SMM_FILE" ] && smm_has_section "Risks"; then
    echo "### Open Questions:"
    smm_section "Risks" 30 | head -20
else
    echo "### Open Questions: none"
fi

echo ""

# Customer intent lives in the Intent pillar
if [ -f "$SMM_FILE" ] && smm_has_section "Intent"; then
    echo "### Customer Intent:"
    smm_section "Intent" 30 | head -20
else
    echo "### Customer Intent: none tracked"
fi
