#!/bin/bash
set -euo pipefail
# Preload for xp-housekeeping: extract open items needing lifecycle review.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"

echo "## Open Items for Review"
echo ""

if [ ! -f "$SMM_FILE" ]; then
    echo "### No SMM available"
    exit 0
fi

# Open goals
if grep -q "## Project Goals" "$SMM_FILE" 2>/dev/null; then
    echo "### Open Goals:"
    grep -A 50 "## Project Goals" "$SMM_FILE" | sed '/^## [^P]/,$d' | head -20
    echo ""
else
    echo "### Open Goals: none"
    echo ""
fi

# Unacknowledged concerns
if grep -q "## Unacknowledged Concerns" "$SMM_FILE" 2>/dev/null; then
    echo "### Unresolved Concerns:"
    grep -A 50 "## Unacknowledged Concerns" "$SMM_FILE" | sed '/^## [^U]/,$d' | head -20
    echo ""
else
    echo "### Unresolved Concerns: none"
    echo ""
fi

# Draft decisions
if grep -q "(draft)" "$SMM_FILE" 2>/dev/null; then
    echo "### Draft Decisions:"
    grep "(draft)" "$SMM_FILE" | head -20
    echo ""
else
    echo "### Draft Decisions: none"
    echo ""
fi

# Technical debt
if grep -q "## Technical Debt" "$SMM_FILE" 2>/dev/null; then
    echo "### Open Technical Debt:"
    grep -A 50 "## Technical Debt" "$SMM_FILE" | sed '/^## [^T]/,$d' | head -20
    echo ""
else
    echo "### Open Technical Debt: none"
    echo ""
fi
