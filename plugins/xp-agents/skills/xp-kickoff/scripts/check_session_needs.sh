#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

RETRO_INPUT="${SMM_DIR}/.retro-input.json"
SPRINT_RETRO_INPUT="${SMM_DIR}/.sprint-retro-input.json"
MARKER="${SMM_DIR}/.needs-kickoff"

echo "SMM_DIR=${SMM_DIR}"
echo ""
echo "## Session Review Status"
echo ""

# 1. Check for retrospective data. Sprint retro takes precedence over
# session retro when both files exist — retrospective.py enforces the
# exclusive-file invariant, but report sprint if anything is off.
if [ -f "$SPRINT_RETRO_INPUT" ]; then
    echo "### SPRINT_RETRO_NEEDED"
    echo "Previous session ended a sprint. Run /xp-run-sprint-retro instead of the regular retro."
    echo ""
elif [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Check for product spec
if [ -f "${SMM_DIR}/.needs-product-spec" ]; then
    echo "### NEEDS_PRODUCT_SPEC"
    echo "No product_spec.md found. Run /xp-product-spec to create one."
    echo ""
fi

# 3. Check for sprint
if [ -f "${SMM_DIR}/.needs-sprint" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
fi

# 4. Sprint status (for work selection context)
SPRINT_FILE="${SMM_DIR}/sprint.md"
if [ -f "$SPRINT_FILE" ]; then
    ready=$(count_sprint_status "ready" "$SPRINT_FILE")
    if [ "$ready" -gt 0 ]; then
        echo "### SPRINT_ACTIVE"
        echo "Sprint has ${ready} ready stories:"
        echo ""
        grep -B2 -F '**Status:** ready' "$SPRINT_FILE" \
            | grep '###' || true
        echo ""
    fi
fi

# Always clear the marker here. This preload runs as a !`command` before
# any tool calls, so the gate must be lifted for the review itself to
# proceed. If the review is aborted, session_start.py will recreate the
# marker on the next session.
rm -f "$MARKER"
