#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: output file paths for agent to Read.
# XP values injected universally via SubagentStart.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# SMM file path (agent reads via Read tool)
SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
if [ -f "$SMM_FILE" ]; then
    echo "SMM_FILE=${SMM_FILE}"
fi

# Sprint file path
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    echo "SPRINT_FILE=${SPRINT_FILE}"
fi

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
    echo "PLAN_FILE=${PLAN_PATH}"
fi

# Clear plan review gate — this reviewer is running
rm -f "$MARKER"
