#!/bin/bash
set -euo pipefail

# Common preload base for XP agent skills.
# Source this from individual preload scripts:
#   source "$(dirname "$0")/../../_preload_base.sh"
#
# After sourcing, PLUGIN_ROOT and SMM_DIR are set.
# Call dump_smm to output the SMM state section.
# Call dump_diff to output git diff stats.

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
    echo "## SMM State: unavailable"
    exit 0
}

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

# Check if a section heading exists in the SMM file.
# Usage: smm_has_section "Intent"
# Requires SMM_FILE to be set by the caller.
# shellcheck disable=SC2153  # SMM_FILE is set by callers, not here
smm_has_section() {
    grep -q "^## ${1}$" "$SMM_FILE" 2>/dev/null
}

# Extract a markdown section from the SMM file by heading name.
# Captures from ^## Name$ until the next ^## heading.
# Usage: smm_section "Intent" [max_lines]
#   smm_section "Risks" 30 | head -20   # display first 20 lines
#   smm_section "Risks" 30 | grep -qi "question"  # search section
# Requires SMM_FILE to be set and the file to exist.
smm_section() {
    local name="$1"
    local max_lines="${2:-50}"
    local first_char="${name:0:1}"
    grep -A "$max_lines" "^## ${name}$" "$SMM_FILE" | \
        sed "/^## [^${first_char}]/,\$d"
}
