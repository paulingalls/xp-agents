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
