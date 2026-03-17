#!/bin/bash
set -euo pipefail
# Preload for xp-session-review: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
RETRO_INPUT="${SMM_DIR}/.retro-input.json"
MARKER="${SMM_DIR}/.needs-session-review"

echo "## Session Review Status"
echo ""

NEEDS_RETRO=false
NEEDS_GOALS=false
NEEDS_HOUSEKEEPING=false

# 1. Check for retrospective data
if [ -f "$RETRO_INPUT" ]; then
    NEEDS_RETRO=true
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Check for goals
if [ -f "$SMM_FILE" ] && grep -q "## Project Goals" "$SMM_FILE" 2>/dev/null; then
    echo "### Goals: PRESENT"
else
    NEEDS_GOALS=true
    echo "### GOALS_NEEDED"
    echo "No project goals recorded yet."
    echo ""
fi

# 3. Check for open items needing housekeeping
HAS_OPEN_ITEMS=false
if [ -f "$SMM_FILE" ]; then
    if grep -q "## Unacknowledged Concerns" "$SMM_FILE" 2>/dev/null; then
        HAS_OPEN_ITEMS=true
    fi
    if grep -q "(draft)" "$SMM_FILE" 2>/dev/null; then
        HAS_OPEN_ITEMS=true
    fi
    if grep -q "## Technical Debt" "$SMM_FILE" 2>/dev/null; then
        HAS_OPEN_ITEMS=true
    fi
fi

if [ "$HAS_OPEN_ITEMS" = true ]; then
    NEEDS_HOUSEKEEPING=true
    echo "### HOUSEKEEPING_NEEDED"
    echo "Open concerns, draft decisions, or technical debt found."
    echo ""
fi

# Summary
if [ "$NEEDS_RETRO" = false ] && [ "$NEEDS_GOALS" = false ] && [ "$NEEDS_HOUSEKEEPING" = false ]; then
    echo "### NONE"
    echo "No session review actions needed."
fi

# Clear the marker since the session review is starting
if [ -f "$MARKER" ]; then
    rm -f "$MARKER"
fi
