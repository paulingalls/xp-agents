#!/bin/bash
set -euo pipefail
# Preload for xp-housekeeping: extract open items from four-pillar SMM.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"

echo "## Open Items for Review"
echo ""

if [ ! -f "$SMM_FILE" ]; then
    echo "### No SMM available"
    exit 0
fi

# Intent pillar (goals, customer input)
if smm_has_section "Intent"; then
    echo "### Intent:"
    smm_section "Intent" | head -20
    echo ""
else
    echo "### Intent: none"
    echo ""
fi

# Constraints pillar (decisions, conventions)
if smm_has_section "Constraints"; then
    echo "### Constraints:"
    smm_section "Constraints" | head -20
    echo ""
else
    echo "### Constraints: none"
    echo ""
fi

# Risks pillar (concerns, assumptions, debt, questions, discoveries)
if smm_has_section "Risks"; then
    echo "### Risks:"
    smm_section "Risks" | head -20
    echo ""
else
    echo "### Risks: none"
    echo ""
fi
