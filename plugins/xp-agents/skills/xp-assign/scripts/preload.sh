#!/bin/bash
set -euo pipefail
# Preload for xp-assign: emit plan/sprint/SMM paths, clear assign gate.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"
echo "SMM_FILE=$(smm_render_to_tempfile)"

# Plan path persisted by xp-review-plan preload
PLAN_MARKER="${SMM_DIR}/.last-plan-path"
if [ -f "$PLAN_MARKER" ]; then
    PLAN_PATH=$(cat "$PLAN_MARKER")
    if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
        echo "PLAN_FILE=${PLAN_PATH}"
    fi
fi

if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# The teammate batch /xp-schedule already promoted: in-progress stories whose
# execution_mode is teammate. Computed in Python (no selection math in the
# skill) — the narrowed xp-assign consumes TEAMMATE_STORY_IDS to split + spawn,
# symmetric with /xp-schedule's FRONTIER_IDS. Always emitted (empty when none).
echo "TEAMMATE_STORY_IDS=$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from pathlib import Path
from sprint_store import load_sprint
sprint = load_sprint(Path(sys.argv[3]))
ids = [] if sprint is None else [
    s["id"] for s in sprint["stories"]
    if s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
]
print(" ".join(ids))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" 2>/dev/null || echo "")"

rm -f "${SMM_DIR}/.assign-pending"
