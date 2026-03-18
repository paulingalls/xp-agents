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

# 1. Check for retrospective data
if [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Check for goals (four-pillar: ## Intent, old: ## Project Goals)
if [ -f "$SMM_FILE" ] && grep -q "^## Intent$\|^## Project Goals$" "$SMM_FILE" 2>/dev/null; then
    echo "### Goals: PRESENT"
else
    echo "### GOALS_NEEDED"
    echo "No project goals recorded yet."
    echo ""
fi

# 3. Housekeeping always runs as the final step
echo "### HOUSEKEEPING"
echo "Housekeeping runs as final step (ensures SMM + behavioral guide injection)."

# Always clear the marker here. This preload runs as a !`command` before
# any tool calls, so the gate must be lifted for the review itself to
# proceed. If the review is aborted, session_start.py will recreate the
# marker on the next session.
rm -f "$MARKER"
