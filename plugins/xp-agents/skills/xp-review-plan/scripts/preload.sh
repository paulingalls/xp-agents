#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: emits file paths for agent to Read.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Plan path from marker set by post_tool_exit_plan.py. When the marker is
# absent (already consumed by a first pass) but .last-plan-path names a file
# that still exists, this is a re-review — the blocking-finding protocol's
# demanded second pass — not a misfire.
#
# ACCEPTED LIMIT: .last-plan-path is NOT session-scoped. A later session with
# no marker falls back to the PREVIOUS session's plan while that file exists,
# so PLAN_SOURCE=last-reviewed carries no freshness guarantee. Accepted because
# xp-assign's preload already reads this same file cross-session — the fallback
# inherits that staleness shape rather than adding a new one.
MARKER="${SMM_DIR}/.plan-awaiting-review"
LAST_PLAN_PATH_FILE="${SMM_DIR}/.last-plan-path"
PLAN_PATH=""
PLAN_SOURCE=""
if [ -f "$MARKER" ]; then
    PLAN_PATH=$(cat "$MARKER")
    PLAN_SOURCE="marker"
elif [ -f "$LAST_PLAN_PATH_FILE" ]; then
    PLAN_PATH=$(cat "$LAST_PLAN_PATH_FILE")
    PLAN_SOURCE="last-reviewed"
fi

# Misfire short-circuit — skip SMM/sprint renders when there's no valid plan.
if [ -z "$PLAN_PATH" ] || [ ! -f "$PLAN_PATH" ]; then
    if [ -f "$MARKER" ]; then
        echo "PLAN_FILE_ERROR=Marker '$(flat "$PLAN_PATH")' invalid. Re-enter plan mode or check ~/.claude/plans/."
        # Clear the stale last-reviewed pointer too — otherwise the NEXT
        # invocation silently resurrects the previously reviewed plan
        # instead of reporting the loud "no plan" error it should.
        rm -f "$LAST_PLAN_PATH_FILE"
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

emit_system_context_rendered_for plan-reviewer

emit_path_var PLAN_FILE "$PLAN_PATH"
emit_var PLAN_SOURCE "$PLAN_SOURCE"
echo "$PLAN_PATH" > "${SMM_DIR}/.last-plan-path"

rm -f "$MARKER"
