#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

RETRO_INPUT="${SMM_DIR}/.retro-input.json"

echo "SMM_DIR=${SMM_DIR}"
echo ""
echo "## Session Review Status"
echo ""

# 1. Check for retrospective data. Sprint sizing is now included in the
# session retro input — no separate sprint retro path.
if [ -f "$RETRO_INPUT" ]; then
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

# 3. Check for execution plan (JSON format, via CLI)
if ! plan_has_remaining; then
    echo "### NEEDS_EXECUTION_PLAN"
    echo "No execution plan with remaining work. Run /xp-plan to create one."
    echo ""
fi

# 4. Check for sprint (marker OR no active stories)
if [ -f "${SMM_DIR}/.needs-sprint" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
elif ! sprint_has_active; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
fi

# 5. Sprint status (for work selection context)
if sprint_has_active; then
    ready_count=$(sprint_count_status ready)
    if [ "$ready_count" -gt 0 ]; then
        echo "### SPRINT_ACTIVE"
        echo "Sprint has ${ready_count} ready stories:"
        echo ""
        sprint_list_stories --status ready
        echo ""
    fi
fi

# .needs-kickoff is cleared by kickoff_gate.py (UserPromptSubmit hook)
# which runs before this preload. It also writes .needs-housekeeping
# so the housekeeping stop gate can enforce housekeeping completion.
