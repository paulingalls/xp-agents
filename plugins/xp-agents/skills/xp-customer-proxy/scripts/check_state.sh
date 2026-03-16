#!/bin/bash
set -euo pipefail

# Deterministic preload for xp-customer-proxy skill.
# Runs via !`command` before the skill content loads.
# Outputs a summary of goals, open questions, and open intents.

PLUGIN_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
    echo "## SMM State: unavailable"
    echo "Could not resolve SMM directory."
    exit 0
}

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
# Always materialize to get current state
python3 "${PLUGIN_ROOT}/smm/materialize.py" >/dev/null 2>&1 || true

echo "## Current SMM State"
echo ""

# Check for goals
if [ -f "$SMM_FILE" ] && grep -q "## Project Goals" "$SMM_FILE" 2>/dev/null; then
    echo "### Goals: PRESENT"
    grep -A 50 "## Project Goals" "$SMM_FILE" | sed '/^## [^P]/,$d' | head -20
else
    echo "### Goals: NONE RECORDED"
    echo "**First-run: Must collect goals from the user.**"
fi

echo ""

# Check for open questions
if [ -f "$SMM_FILE" ] && grep -q "Blocking Questions\|## Questions" "$SMM_FILE" 2>/dev/null; then
    echo "### Open Questions:"
    grep -A 30 "Questions" "$SMM_FILE" | sed '/^## [^Q]/,$d' | head -20
else
    echo "### Open Questions: none"
fi

echo ""

# Check for customer intent
if [ -f "$SMM_FILE" ] && grep -q "## Customer Intent" "$SMM_FILE" 2>/dev/null; then
    echo "### Customer Intent:"
    grep -A 30 "## Customer Intent" "$SMM_FILE" | sed '/^## [^C]/,$d' | head -20
else
    echo "### Customer Intent: none tracked"
fi
