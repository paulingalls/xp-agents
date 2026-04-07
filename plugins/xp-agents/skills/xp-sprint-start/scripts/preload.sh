#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-start: show planned features and sprint state.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# --- Check product_spec.md exists ---
SPEC_FILE="${SMM_DIR}/product_spec.md"
if [ ! -f "$SPEC_FILE" ]; then
    echo "## ERROR: No product_spec.md found"
    echo "Run /xp-product-spec first to create a product spec."
    exit 0
fi

# --- Check for [planned] features ---
planned=$(grep -c '\[planned\]' "$SPEC_FILE" 2>/dev/null || true)
planned=${planned:-0}
if [ "$planned" -eq 0 ]; then
    echo "## ERROR: No [planned] features in product_spec.md"
    echo "All features are delivered. Add new features via /xp-product-spec."
    exit 0
fi

# --- Show planned features ---
delivered=$(grep -c '\[delivered:' "$SPEC_FILE" 2>/dev/null || true)
delivered=${delivered:-0}
echo "## Planned Features (${planned} planned, ${delivered} delivered)"
echo "PRODUCT_SPEC=${SPEC_FILE}"

# --- Check for deferred stories in existing sprint ---
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    deferred=$(grep -c 'Status:.*\bdeferred\b' "$SPRINT_FILE" 2>/dev/null || true)
    deferred=${deferred:-0}
    if [ "$deferred" -gt 0 ]; then
        echo ""
        echo "## Deferred Stories from Previous Sprint (${deferred})"
        echo ""
        # Show deferred story sections
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
