#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: plan file + SMM + sprint + XP values.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_smm
echo ""
# Sprint context for scope alignment and execution mode assessment
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    echo ""
    cat "$SPRINT_FILE"
fi
echo ""
dump_values

# Read plan file path from marker, fall back to most recent .claude/plans/*.md
MARKER="${SMM_DIR}/.plan-awaiting-review"
PLAN_PATH=""
if [ -f "$MARKER" ]; then
    PLAN_PATH=$(cat "$MARKER")
fi

# If marker didn't contain a valid file path, glob for the latest plan
if [ -z "$PLAN_PATH" ] || [ ! -f "$PLAN_PATH" ]; then
    # shellcheck disable=SC2012
    PLAN_PATH=$(ls -t ~/.claude/plans/*.md 2>/dev/null | head -1)
fi

if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    echo ""
    echo "## Plan to Review"
    cat "$PLAN_PATH"
else
    echo ""
    echo "## Plan to Review: not found"
    echo "No plan file available. Check the conversation context for the plan."
fi

# Clear plan review gate — this reviewer is running
rm -f "$MARKER"
