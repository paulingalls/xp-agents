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

# Read plan file path from marker (set by post_tool_exit_plan.py with
# ExitPlanMode tool_response.filePath — the actual plan path for this session)
MARKER="${SMM_DIR}/.plan-awaiting-review"
PLAN_PATH=""
if [ -f "$MARKER" ]; then
    PLAN_PATH=$(cat "$MARKER")
fi

if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    echo "PLAN_FILE=${PLAN_PATH}"
    # Persist plan path for xp-assign (marker is cleared below)
    echo "$PLAN_PATH" > "${SMM_DIR}/.last-plan-path"
elif [ -f "$MARKER" ]; then
    echo "WARNING: .plan-awaiting-review marker exists but path is invalid: '${PLAN_PATH}'"
    echo "PLAN_FILE_ERROR=Marker exists but plan file not found at '${PLAN_PATH}'. The agent should re-enter plan mode or check ~/.claude/plans/ manually."
else
    echo "WARNING: No .plan-awaiting-review marker found — plan review invoked without a plan."
    echo "PLAN_FILE_ERROR=No plan marker found. Run EnterPlanMode/ExitPlanMode first to create a plan."
fi

# Clear plan review gate — this reviewer is running
rm -f "$MARKER"

# Size-floor check: M stories with >15 projected files must be L or split.
if [ -f "${SMM_DIR}/sprint.json" ]; then
    VIOLATIONS=$(python3 -c '
import json, re, sys
sprint = json.load(open(sys.argv[1]))
violations = []
for s in sprint.get("stories", []):
    if s.get("size") != "M":
        continue
    domain = s.get("file_domain", [])
    projected = 0
    for f in domain:
        if re.match(r"plugins/xp-agents/scripts/[^/]+\.py$", f):
            projected += 1
    total = len(domain) + projected
    if total > 15:
        sid = s["id"]
        violations.append(
            f"size floor violation: {sid} declares {total} files"
            f" at size M; must be L or split."
        )
print(json.dumps(violations))
' "${SMM_DIR}/sprint.json" 2>/dev/null || echo "[]")
    echo "size_floor_violations=${VIOLATIONS}"
fi
