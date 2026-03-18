#!/bin/bash
set -euo pipefail

# Common preload base for XP agent skills.
# Source this from individual preload scripts:
#   source "$(dirname "$0")/../../_preload_base.sh"
#
# After sourcing, PLUGIN_ROOT and SMM_DIR are set.
# SMM is materialized and SHARED_MENTAL_MODEL.md is current.
# Call dump_smm to output the SMM state section.
# Call dump_diff to output git diff stats.

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
    echo "## SMM State: unavailable"
    exit 0
}

# Materialize only if no curated SMM exists yet (prevents overwriting four-pillar SMM)
if [ ! -f "${SMM_DIR}/.curation-watermark" ]; then
    python3 "${PLUGIN_ROOT}/smm/materialize.py" >/dev/null 2>&1 || true
fi

dump_smm() {
    local smm_file="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
    if [ -f "$smm_file" ]; then
        echo "## Current SMM State"
        cat "$smm_file"
    else
        echo "## SMM State: no materialized view"
    fi
}

dump_diff() {
    echo "## Recent Changes"
    git diff HEAD~1 --stat 2>/dev/null || echo "(no recent diff available)"
    echo ""
}
