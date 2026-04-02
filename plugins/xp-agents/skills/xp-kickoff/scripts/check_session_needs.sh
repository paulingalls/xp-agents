#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
RETRO_INPUT="${SMM_DIR}/.retro-input.json"
MARKER="${SMM_DIR}/.needs-kickoff"

echo "SMM_DIR=${SMM_DIR}"
echo ""
echo "## Session Review Status"
echo ""

# 1. Check for retrospective data
if [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

if [ -f "${SMM_DIR}/.needs-product-spec" ]; then
    echo "### NEEDS_PRODUCT_SPEC"
    echo "No product_spec.md found. Run /xp-product-spec to create one."
    echo ""
fi

if [ -f "${SMM_DIR}/.needs-sprint" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
fi

SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    ready_count=$(grep -cF '**Status:** ready' "$SPRINT_FILE" 2>/dev/null || true)
    ready_count=${ready_count:-0}
    if [ "$ready_count" -gt 0 ]; then
        echo "### SPRINT_ACTIVE"
        echo "Sprint has ${ready_count} ready stories:"
        echo ""
        grep -B2 -F '**Status:** ready' "$SPRINT_FILE" | grep '###' || true
        echo ""
    fi
fi

# 2. Always show goals and offer to add more
echo "### GOALS_REVIEW"
if [ -f "$SMM_FILE" ] && smm_has_section "Intent"; then
    echo "Current goals:"
    smm_section "Intent" | head -20
else
    echo "No project goals recorded yet."
fi
echo ""

# 3. Check for open questions or Try items needing triage
echo "### QUESTIONS_CHECK"
QUESTIONS_FOUND=false
if [ -f "$SMM_FILE" ] && smm_has_section "Risks"; then
    if smm_section "Risks" 30 | grep -qi "question\|assumption\|blocking"; then
        QUESTIONS_FOUND=true
    fi
fi
if [ "$QUESTIONS_FOUND" = false ] && [ -f "${SMM_DIR}/events.jsonl" ]; then
    if grep -q '"type": "question"' "${SMM_DIR}/events.jsonl" 2>/dev/null; then
        QUESTIONS_FOUND=true
    fi
fi
# Check for Try items from latest retro
if [ "$QUESTIONS_FOUND" = false ]; then
    RETRO_DIR="${SMM_DIR}/retrospectives"
    if [ -d "$RETRO_DIR" ]; then
        LATEST_RETRO=$(find "$RETRO_DIR" -maxdepth 1 -name "*.json" 2>/dev/null | sort -r | head -1)
        if [ -n "$LATEST_RETRO" ]; then
            HAS_TRIES=$(python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
print('yes' if data.get('try', []) else 'no')
" "$LATEST_RETRO" 2>/dev/null || echo "no")
            if [ "$HAS_TRIES" = "yes" ]; then
                QUESTIONS_FOUND=true
            fi
        fi
    fi
fi
if [ "$QUESTIONS_FOUND" = true ]; then
    echo "QUESTIONS_NEEDED"
    echo "Open questions, assumptions, or Try items to review."
else
    echo "No open questions or Try items."
fi
echo ""

# 4. Housekeeping always runs as the final step
echo "### HOUSEKEEPING"
echo "Housekeeping runs as final step (ensures SMM + behavioral guide injection)."

# Always clear the marker here. This preload runs as a !`command` before
# any tool calls, so the gate must be lifted for the review itself to
# proceed. If the review is aborted, session_start.py will recreate the
# marker on the next session.
rm -f "$MARKER"
