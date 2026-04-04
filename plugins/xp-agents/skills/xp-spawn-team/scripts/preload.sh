#!/bin/bash
set -euo pipefail
# Preload for xp-spawn-team: SMM + sprint + plan + guide.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"
echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_smm

# Sprint data
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    echo ""
    echo "## Sprint Data"
    cat "$SPRINT_FILE"
else
    echo ""
    echo "## Sprint Data: not found"
    echo "No sprint.md available. Cannot analyze stories for team spawning."
fi

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
    echo ""
    echo "## Current Plan"
    cat "$PLAN_PATH"
else
    echo ""
    echo "## Current Plan: not found"
    echo "No plan file available. Cannot structure tasks for team spawning."
fi

dump_guide
