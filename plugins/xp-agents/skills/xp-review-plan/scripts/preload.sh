#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: emits file paths for agent to Read.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Plan path from marker set by post_tool_exit_plan.py.
MARKER="${SMM_DIR}/.plan-awaiting-review"
PLAN_PATH=""
[ -f "$MARKER" ] && PLAN_PATH=$(cat "$MARKER")

# Misfire short-circuit — skip SMM/sprint renders when there's no valid plan.
if [ -z "$PLAN_PATH" ] || [ ! -f "$PLAN_PATH" ]; then
    if [ -f "$MARKER" ]; then
        echo "PLAN_FILE_ERROR=Marker '${PLAN_PATH}' invalid. Re-enter plan mode or check ~/.claude/plans/."
    else
        echo "PLAN_FILE_ERROR=No plan marker. Run EnterPlanMode/ExitPlanMode first."
    fi
    rm -f "$MARKER"
    exit 0
fi

if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
    echo "SMM_FILE=$(smm_render_to_tempfile)"
fi

if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

echo "PLAN_FILE=${PLAN_PATH}"
echo "$PLAN_PATH" > "${SMM_DIR}/.last-plan-path"

rm -f "$MARKER"
