#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

RETRO_INPUT="${SMM_DIR}/.retro-input.json"
SPRINT_RETRO_INPUT="${SMM_DIR}/.sprint-retro-input.json"
MARKER="${SMM_DIR}/.needs-kickoff"

echo "SMM_DIR=${SMM_DIR}"
echo ""
echo "## Session Review Status"
echo ""

# 1. Check for retrospective data. Sprint retro takes precedence over
# session retro when both files exist — retrospective.py enforces the
# exclusive-file invariant, but report sprint if anything is off.
if [ -f "$SPRINT_RETRO_INPUT" ]; then
    echo "### SPRINT_RETRO_NEEDED"
    echo "Previous session ended a sprint. Run /xp-run-sprint-retro instead of the regular retro."
    echo ""
elif [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Check for system context
SYSTEM_CONTEXT="${SMM_DIR}/system_context.md"
if [ ! -f "$SYSTEM_CONTEXT" ] || [ -L "$SYSTEM_CONTEXT" ]; then
    echo "### NEEDS_SYSTEM_CONTEXT"
    echo "No system_context.md found. Run /xp-system-context to create one."
    echo ""
fi

# 3. Check for execution plan
EXEC_PLAN="${SMM_DIR}/execution_plan.md"
if [ ! -f "$EXEC_PLAN" ] || [ -L "$EXEC_PLAN" ]; then
    echo "### NEEDS_EXECUTION_PLAN"
    echo "No execution_plan.md found. Run /xp-plan to create one."
    echo ""
fi

# 4. Check for sprint (marker OR no active stories)
SPRINT_FILE="${SMM_DIR}/sprint.md"
ready=0
if [ -f "$SPRINT_FILE" ]; then
    ready=$(count_sprint_status "ready" "$SPRINT_FILE")
fi

if [ -f "${SMM_DIR}/.needs-sprint" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
elif [ ! -f "$SPRINT_FILE" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
elif [ "$ready" -eq 0 ]; then
    in_prog=$(count_sprint_status "in-progress" "$SPRINT_FILE")
    if [ "$in_prog" -eq 0 ]; then
        echo "### NEEDS_SPRINT"
        echo "No active sprint. Run /xp-sprint-start to plan a sprint."
        echo ""
    fi
fi

# 5. Sprint status (for work selection context)
if [ "$ready" -gt 0 ]; then
    echo "### SPRINT_ACTIVE"
    echo "Sprint has ${ready} ready stories:"
    echo ""
    grep -B2 -F '**Status:** ready' "$SPRINT_FILE" \
        | grep '###' || true
    echo ""
fi

# Always clear the marker here. This preload runs as a !`command` before
# any tool calls, so the gate must be lifted for the review itself to
# proceed. If the review is aborted, session_start.py will recreate the
# marker on the next session.
rm -f "$MARKER"
