#!/bin/bash
set -euo pipefail
# Preload for xp-accept: show in-progress stories for verification.
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

in_progress_count=$(sprint_count_status in-progress)

if [ "$in_progress_count" -eq 0 ]; then
    echo "### NO_IN_PROGRESS"
    echo "No in-progress stories to accept."
    exit 0
fi

# Clear the accept gate marker so update-story done is unblocked.
# This MUST happen in the preload, not via rm in the SKILL.md — never
# ask an agent to run rm.
consume_marker ACCEPT

echo "### STORIES_TO_ACCEPT"
echo "Sprint has ${in_progress_count} in-progress stories to verify."
echo "SPRINT_FILE=${SPRINT_FILE}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"

# Surface open concerns overlapping in-progress stories' file domains
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python3 "${SKILL_DIR}/scripts/concern_triage.py" --smm-dir "${SMM_DIR}" --sprint-file "${SPRINT_FILE}" || true
echo ""

# Surface acceptance_execution type per in-progress story
python3 "${SKILL_DIR}/scripts/acceptance_types.py" --sprint-file "${SPRINT_FILE}" || true
echo ""

# Detect teammate worktrees — emits `story-id: abs-path` per live worktree
# so the SKILL prose can cd into each story's worktree before running its
# acceptance command (the unmerged teammate edits live there).
teammate_wts=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" --smm-dir "${SMM_DIR}" \
    list-teammate-worktree-paths --cwd . 2>/dev/null || true)
if [ -n "$teammate_wts" ]; then
    echo ""
    echo "### TEAMMATE_WORKTREES"
    echo "$teammate_wts"
fi
