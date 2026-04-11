#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-start: show milestones and sprint state.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# --- Check for execution_plan.json ---
PLAN_FILE="${SMM_DIR}/execution_plan.json"

if ! plan_exists; then
    echo "## ERROR: No execution_plan.json found"
    echo "Run /xp-plan to create an execution plan."
    exit 0
fi

if ! plan_has_remaining; then
    echo "## ERROR: No [planned] or [in-progress] milestones"
    echo "All milestones are delivered. Add new milestones via /xp-plan."
    exit 0
fi

counts=$(plan_count)
echo "## Execution Plan (${counts})"
echo "EXECUTION_PLAN=${PLAN_FILE}"

# --- Check for system context ---
check_system_context

# --- Check for deferred stories in existing sprint ---
if sprint_exists; then
    deferred_count=$(sprint_count_status deferred)
    if [ "$deferred_count" -gt 0 ]; then
        echo ""
        echo "## Deferred Stories from Previous Sprint (${deferred_count})"
        echo ""
        sprint_list_stories --status deferred
    fi
fi

# --- Determine next sprint ID ---
EVENTS_FILE="${SMM_DIR}/events.jsonl"
sprint_count=0
if [ -f "$EVENTS_FILE" ]; then
    sprint_count=$(grep -c '"action": "start"' "$EVENTS_FILE" 2>/dev/null || true)
    sprint_count=${sprint_count:-0}
fi
next_num=$((sprint_count + 1))
printf -v NEXT_SPRINT_ID "sprint-%03d" "$next_num"
echo ""
echo "NEXT_SPRINT_ID=${NEXT_SPRINT_ID}"
