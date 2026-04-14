#!/bin/bash
set -euo pipefail
# Preload for xp-plan: detect create vs update mode, count milestones.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

PLAN_FILE="${SMM_DIR}/execution_plan.json"

if plan_exists; then
    counts=$(plan_count)
    echo "## Existing Execution Plan"
    echo "${counts}"
    echo "EXECUTION_PLAN=${PLAN_FILE}"
else
    echo "## No execution plan found"
    echo "Create mode: gather sources and decompose into milestones."
fi

# Check system context availability — xp-plan needs the NEEDS flag
CTX_FILE="${SMM_DIR}/system_context.md"
if [ -f "$CTX_FILE" ] && [ ! -L "$CTX_FILE" ]; then
    echo ""
    echo "SYSTEM_CONTEXT=${CTX_FILE}"
else
    echo ""
    echo "NEEDS_SYSTEM_CONTEXT=true"
fi
