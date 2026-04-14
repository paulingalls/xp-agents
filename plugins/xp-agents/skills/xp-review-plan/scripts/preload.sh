#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: output file paths for agent to Read.
# XP values injected universally via SubagentStart.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# SMM rendered to tempfile (agent reads via Read tool)
if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
    echo "SMM_FILE=$(smm_render_to_tempfile)"
fi

# Sprint rendered to tempfile (read-only consumer — rendered markdown saves tokens)
if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
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
    PLAN_PATH=$(ls -t ~/.claude/plans/*.md 2>/dev/null | head -1 || true)
fi

if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    echo "PLAN_FILE=${PLAN_PATH}"
    # Persist plan path for xp-assign (marker is cleared below)
    echo "$PLAN_PATH" > "${SMM_DIR}/.last-plan-path"
fi

# Clear plan review gate — this reviewer is running
rm -f "$MARKER"
