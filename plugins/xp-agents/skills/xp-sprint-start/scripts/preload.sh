#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-start: show milestones or features and sprint state.
# Supports both execution_plan.md (new) and product_spec.md (legacy).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# --- Check for execution_plan.md (preferred) or product_spec.md (legacy) ---
PLAN_FILE="${SMM_DIR}/execution_plan.md"
SPEC_FILE="${SMM_DIR}/product_spec.md"

if [ -f "$PLAN_FILE" ] && [ ! -L "$PLAN_FILE" ]; then
    # New path: execution plan with milestones
    planned=$(grep -c '\[planned\]' "$PLAN_FILE" 2>/dev/null || echo 0)
    in_progress=$(grep -c '\[in-progress\]' "$PLAN_FILE" 2>/dev/null || echo 0)
    delivered=$(grep -c '\[delivered:' "$PLAN_FILE" 2>/dev/null || echo 0)

    if [ "$planned" -eq 0 ] && [ "$in_progress" -eq 0 ]; then
        echo "## ERROR: No [planned] or [in-progress] milestones in execution_plan.md"
        echo "All milestones are delivered. Add new milestones via /xp-plan."
        exit 0
    fi

    echo "## Execution Plan (${planned} planned, ${in_progress} in-progress, ${delivered} delivered)"
    echo "EXECUTION_PLAN=${PLAN_FILE}"

elif [ -f "$SPEC_FILE" ]; then
    # Legacy path: product spec with features
    planned=$(grep -c '\[planned\]' "$SPEC_FILE" 2>/dev/null || true)
    planned=${planned:-0}
    if [ "$planned" -eq 0 ]; then
        echo "## ERROR: No [planned] features in product_spec.md"
        echo "All features are delivered. Add new features via /xp-product-spec."
        exit 0
    fi

    delivered=$(grep -c '\[delivered:' "$SPEC_FILE" 2>/dev/null || true)
    delivered=${delivered:-0}
    echo "## Planned Features (${planned} planned, ${delivered} delivered)"
    echo "PRODUCT_SPEC=${SPEC_FILE}"

else
    echo "## ERROR: No execution_plan.md or product_spec.md found"
    echo "Run /xp-plan to create an execution plan, or /xp-product-spec for a product spec."
    exit 0
fi

# --- Check for system context ---
check_system_context

# --- Check for deferred stories in existing sprint ---
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    deferred=$(grep -c 'Status:.*\bdeferred\b' "$SPRINT_FILE" 2>/dev/null || true)
    deferred=${deferred:-0}
    if [ "$deferred" -gt 0 ]; then
        echo ""
        echo "## Deferred Stories from Previous Sprint (${deferred})"
        echo ""
        grep -B2 'Status:.*\bdeferred\b' "$SPRINT_FILE" || true
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
