#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt for changed files.
# SMM is already in context (inline skill, not forked).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Auto-detect a teammate worktree during /xp-accept fix-cycles so dump_diff
# captures the teammate's actual edits instead of the orchestrator's
# incidental cwd state. Trigger: ACCEPT_ACTIVE marker present + exactly
# one in-motion (in-progress / reviewing) story whose teammate worktree is
# live. Multiple matches are ambiguous (we don't know which one the
# operator is fixing) — fall back to plain orchestrator cwd. An
# explicitly-set TEAMMATE_CWD always wins so callers who know better than
# the heuristic can override it.
if [ -z "${TEAMMATE_CWD:-}" ]; then
    TEAMMATE_CWD=$(python3 - <<EOF 2>/dev/null
import sys
from pathlib import Path
sys.path.insert(0, "${PLUGIN_ROOT}/smm")
sys.path.insert(0, "${PLUGIN_ROOT}/scripts")
import sprint_store, worktree
from marker_names import ACCEPT_ACTIVE
from sprint_schema import IN_MOTION_STORY_STATUSES
smm = Path("${SMM_DIR}")
if not (smm / ACCEPT_ACTIVE).exists():
    sys.exit(0)
sprint = sprint_store.load_sprint(smm)
if sprint is None:
    sys.exit(0)
fix_ids = {s["id"] for s in sprint.get("stories", [])
           if s.get("status") in IN_MOTION_STORY_STATUSES}
matches = [p for sid, p in worktree.list_live_teammate_worktree_paths(".")
           if sid in fix_ids]
if len(matches) == 1:
    print(matches[0])
EOF
)
    export TEAMMATE_CWD
fi

echo "SMM_DIR=${SMM_DIR}"
echo "TEAMMATE_CWD=${TEAMMATE_CWD:-}"
echo ""
dump_diff

# Surface debt events for changed files
echo ""
echo "## Technical Debt and Concerns for Changed Files"
changed_files=$(get_changed_files)
if [ -z "$changed_files" ]; then
    echo "(no changed files detected)"
else
    # shellcheck disable=SC2086
    python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/debt_for_files.py" \
        --smm-dir "$SMM_DIR" $changed_files 2>/dev/null || echo "(debt lookup unavailable)"
fi

# Surface unresolved plan review concerns
echo ""
echo "## Open Plan Review Concerns"
python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/open_plan_concerns.py" \
    --smm-dir "$SMM_DIR" 2>/dev/null || echo "(concern lookup unavailable)"
