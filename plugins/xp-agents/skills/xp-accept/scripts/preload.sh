#!/bin/bash
set -euo pipefail
# Preload for xp-accept: show in-progress stories for verification.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SPRINT_FILE="${SMM_DIR}/sprint.md"

echo "SMM_DIR=${SMM_DIR}"
echo ""

if [ ! -f "$SPRINT_FILE" ]; then
    echo "### ERROR"
    echo "No sprint.md found. Nothing to accept."
    exit 0
fi

in_progress_count=$(grep -cF '**Status:** in-progress' "$SPRINT_FILE" 2>/dev/null || true)
in_progress_count=${in_progress_count:-0}

if [ "$in_progress_count" -eq 0 ]; then
    echo "### NO_IN_PROGRESS"
    echo "No in-progress stories to accept."
    exit 0
fi

echo "### STORIES_TO_ACCEPT"
echo "Sprint has ${in_progress_count} in-progress stories to verify:"
echo ""
cat "$SPRINT_FILE"
