#!/bin/bash
set -euo pipefail
# Preload for xp-accept: reviewing-first dispatch with in-progress fallback.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SPRINT_FILE="${SMM_DIR}/sprint.json"

echo "SMM_DIR=${SMM_DIR}"
echo ""

if ! sprint_exists; then
    echo "### ERROR"
    echo "No sprint.json found. Nothing to accept."
    exit 0
fi

# Reviewing-first: teammate self-promote lands stories in `reviewing`;
# solo work leaves them in `in-progress`. Process finished teammate work
# before any in-progress fallback when both coexist.
reviewing_count=$(sprint_count_status reviewing)
in_progress_count=$(sprint_count_status in-progress)

if [ "$reviewing_count" -gt 0 ]; then
    SELECTED_STATUS=reviewing
    SELECTED_COUNT=$reviewing_count
elif [ "$in_progress_count" -gt 0 ]; then
    SELECTED_STATUS=in-progress
    SELECTED_COUNT=$in_progress_count
else
    echo "### NO_STORIES_TO_ACCEPT"
    echo "No reviewing or in-progress stories to accept."
    exit 0
fi

# Clear the ACCEPT marker here so update-story done is unblocked; the agent
# is never asked to run rm.
consume_marker ACCEPT

echo "### STORIES_TO_ACCEPT"
echo "Sprint has ${SELECTED_COUNT} ${SELECTED_STATUS} stories to verify."
echo "SELECTED_STATUS=${SELECTED_STATUS}"
echo "SPRINT_FILE=${SPRINT_FILE}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python3 "${SKILL_DIR}/scripts/concern_triage.py" --smm-dir "${SMM_DIR}" --sprint-file "${SPRINT_FILE}" || true
echo ""

python3 "${SKILL_DIR}/scripts/acceptance_types.py" --sprint-file "${SPRINT_FILE}" || true
echo ""

# Tab-delimited `story-id<TAB>abs-path` per live teammate worktree (macOS
# paths can contain spaces). The SKILL prose cd's into each before
# running its acceptance command.
teammate_wts=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" --smm-dir "${SMM_DIR}" \
    list-teammate-worktree-paths --cwd . 2>/dev/null || true)
if [ -n "$teammate_wts" ]; then
    echo ""
    echo "### TEAMMATE_WORKTREES"
    echo "$teammate_wts"
fi
