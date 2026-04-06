#!/bin/bash
set -euo pipefail

# Common preload base for XP agent skills.
# Source this from individual preload scripts:
#   source "$(dirname "$0")/../../_preload_base.sh"
#
# After sourcing, PLUGIN_ROOT and SMM_DIR are set.
# Call dump_smm to output the SMM state section.
# Call dump_values to output XP values only.
# Call dump_guide to output XP values + process guide.
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

dump_values() {
    local values="${PLUGIN_ROOT}/XP_VALUES.md"
    if [ -f "$values" ]; then
        echo ""
        echo "## XP Values"
        cat "$values"
    else
        echo "## XP Values: not found"
    fi
}

dump_guide() {
    local values="${PLUGIN_ROOT}/XP_VALUES.md"
    local process="${PLUGIN_ROOT}/PROCESS_GUIDE.md"
    if [ -f "$values" ] || [ -f "$process" ]; then
        echo ""
        echo "## Behavioral Guide"
        [ -f "$values" ] && cat "$values"
        [ -f "$process" ] && { echo ""; cat "$process"; }
    else
        echo "## Behavioral Guide: not found"
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

# Find the latest retrospective JSON file.
# Usage: get_latest_retro "$RETRO_DIR"
# Returns path on stdout, empty string if none found.
get_latest_retro() {
    find "$1" -maxdepth 1 -name "*.json" 2>/dev/null | sort -r | head -1
}

# Extract Try items from a retrospective JSON file.
# Usage: get_try_items "$RETRO_FILE"
# Outputs "- <content>" lines, empty if none.
get_try_items() {
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
items = data.get('try', [])
for item in items:
    c = item.get('content', item) if isinstance(item, dict) else item
    print(f'- {c}')
" "$1" 2>/dev/null || true
}

# Count stories with a given status in sprint.md.
# Usage: count_sprint_status "ready" "$SPRINT_FILE"
count_sprint_status() {
    grep -cF "**Status:** $1" "$2" 2>/dev/null || echo 0
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
