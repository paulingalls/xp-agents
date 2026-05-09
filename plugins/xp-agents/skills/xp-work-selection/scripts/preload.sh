#!/bin/bash
set -euo pipefail
# Preload for xp-work-selection: gather Try items, questions, sprint, intent.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# Set .needs-housekeeping here (not in kickoff_gate) so the stop gate
# only activates right before housekeeping runs — not during the entire
# kickoff flow where the agent may need to stop for user input.
write_marker NEEDS_HOUSEKEEPING "kickoff"

# Try items from latest retrospective
RETRO_DIR="${SMM_DIR}/retrospectives"
if [ -d "$RETRO_DIR" ]; then
    LATEST=$(get_latest_retro "$RETRO_DIR")
    if [ -n "$LATEST" ]; then
        TRIES=$(get_try_items "$LATEST")
        if [ -n "$TRIES" ]; then
            echo "### Previous Try Items"
            echo "$TRIES"
            echo ""
        fi
    fi
fi

# Triage: unresolved debts, concerns, questions from events
python3 "${PLUGIN_ROOT}/skills/xp-work-selection/scripts/triage_preload.py" \
    --smm-dir "$SMM_DIR" 2>/dev/null || true
echo ""

# Sprint Status — counts line is the SKILL.md key; bare ID list speaks for itself.
if sprint_exists; then
    ready=$(sprint_count_status ready || echo 0)
    ready=${ready:-0}
    in_prog=$(sprint_count_status in-progress || echo 0)
    in_prog=${in_prog:-0}
    echo "### Sprint Status"
    echo "Ready: ${ready}, In-Progress: ${in_prog}"
    if [ "$ready" -gt 0 ]; then
        echo ""
        sprint_list_stories --status ready
    fi
    echo ""
else
    echo "No Active Sprint"
    echo ""
fi

# Customer Intent
if smm_has_section "Intent"; then
    echo "### Customer Intent"
    smm_section "Intent"
    echo ""
fi
