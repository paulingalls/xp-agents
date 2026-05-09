#!/bin/bash
set -euo pipefail
# Preload for xp-plan: detect create vs update mode, count milestones.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

PLAN_FILE="${SMM_DIR}/execution_plan.json"

if plan_exists; then
    echo "## Existing Execution Plan"
    plan_count
    echo "EXECUTION_PLAN=${PLAN_FILE}"
else
    echo "## No execution plan found"
fi

# xp-plan needs the NEEDS flag — check_system_context only emits the path.
echo ""
if [ -f "$SYSTEM_CONTEXT_FILE" ] && [ ! -L "$SYSTEM_CONTEXT_FILE" ]; then
    echo "SYSTEM_CONTEXT=${SYSTEM_CONTEXT_FILE}"
else
    echo "NEEDS_SYSTEM_CONTEXT=true"
fi
