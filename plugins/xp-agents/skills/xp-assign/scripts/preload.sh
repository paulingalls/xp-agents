#!/bin/bash
set -euo pipefail
# Preload for xp-assign: output plan + sprint + SMM paths and clear assign gate.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"

# SMM for mode selection context
if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
    echo "SMM_FILE=$(smm_render_to_tempfile)"
fi

# Plan file — read path persisted by xp-review-plan preload
PLAN_MARKER="${SMM_DIR}/.last-plan-path"
if [ -f "$PLAN_MARKER" ]; then
    PLAN_PATH=$(cat "$PLAN_MARKER")
    if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
        echo "PLAN_FILE=${PLAN_PATH}"
    fi
fi

# Sprint data — optional context for story tracking
if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# Clear assign gate — this skill is running
rm -f "${SMM_DIR}/.assign-pending"
