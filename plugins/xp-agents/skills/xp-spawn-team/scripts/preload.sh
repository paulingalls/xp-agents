#!/bin/bash
set -euo pipefail
# Preload for xp-spawn-team: plan + sprint + SMM pillars.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
echo "SMM_DIR=${SMM_DIR}"
echo ""

# Constraints + Wisdom pillars for task context
SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
if [ -f "$SMM_FILE" ]; then
    echo "## SMM Constraints"
    smm_section "Constraints"
    echo ""
    echo "## SMM Wisdom"
    smm_section "Wisdom"
    echo ""
fi

# Sprint stories — the tasks to decompose into parallel work
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    echo "## Sprint Data"
    cat "$SPRINT_FILE"
else
    echo "## Sprint Data: not found"
fi
echo ""

# Current plan — check marker first, fall back to most recent
MARKER="${SMM_DIR}/.plan-awaiting-review"
PLAN_PATH=""
if [ -f "$MARKER" ]; then
    PLAN_PATH=$(cat "$MARKER")
fi
if [ -z "$PLAN_PATH" ] || [ ! -f "$PLAN_PATH" ]; then
    # shellcheck disable=SC2012
    PLAN_PATH=$(ls -t ~/.claude/plans/*.md 2>/dev/null | head -1)
fi

if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    echo "## Current Plan"
    cat "$PLAN_PATH"
else
    echo "## Current Plan: not found"
    echo "No plan file available. Cannot structure tasks for team spawning."
fi
