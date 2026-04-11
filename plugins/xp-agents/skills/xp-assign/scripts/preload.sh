#!/bin/bash
set -euo pipefail
# Preload for xp-assign: output sprint + SMM paths and clear assign gate.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# SMM for mode selection context
if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
    echo "SMM_FILE=$(smm_render_to_tempfile)"
fi

# Sprint data — needed for story analysis
if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# Most recent plan file (for context, not gated)
# shellcheck disable=SC2012
PLAN_PATH=$(ls -t ~/.claude/plans/*.md 2>/dev/null | head -1)
if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    echo "PLAN_FILE=${PLAN_PATH}"
fi

# Clear assign gate — this skill is running
rm -f "${SMM_DIR}/.assign-pending"
