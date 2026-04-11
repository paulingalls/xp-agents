#!/bin/bash
set -euo pipefail
# Preload for xp-work-selection: gather Try items, questions, sprint, intent.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# 1. Previous Try Items from latest retrospective
RETRO_DIR="${SMM_DIR}/retrospectives"
if [ -d "$RETRO_DIR" ]; then
    LATEST=$(get_latest_retro "$RETRO_DIR")
    if [ -n "$LATEST" ]; then
        TRIES=$(get_try_items "$LATEST")
        if [ -n "$TRIES" ]; then
            echo "### Previous Try Items:"
            echo "$TRIES"
            echo ""
        fi
    fi
fi

# 2. Open Questions from Risks pillar
if smm_has_section "Risks"; then
    echo "### Open Questions:"
    smm_section "Risks"
    echo ""
fi

# 3. Sprint Status
if sprint_exists; then
    ready=$(sprint_count_status ready || echo 0)
    ready=${ready:-0}
    in_prog=$(sprint_count_status in-progress || echo 0)
    in_prog=${in_prog:-0}
    echo "### Sprint Status"
    echo "Ready: ${ready}, In-Progress: ${in_prog}"
    if [ "$ready" -gt 0 ]; then
        echo ""
        echo "Ready stories:"
        sprint_list_stories --status ready
    fi
    echo ""
else
    echo "### No Active Sprint"
    echo ""
fi

# 4. Customer Intent
if smm_has_section "Intent"; then
    echo "### Customer Intent:"
    smm_section "Intent"
    echo ""
fi
