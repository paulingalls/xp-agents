#!/bin/bash
set -euo pipefail

# Common preload base for XP agent skills.
# Source this from individual preload scripts:
#   source "$(dirname "$0")/../../_preload_base.sh"
#
# After sourcing, PLUGIN_ROOT and SMM_DIR are set.
# Call dump_smm to output the SMM state section.
# Call dump_values to output XP values only.
# Call dump_diff to output git diff stats (or dump_diff full for complete diffs).
# Call get_changed_files to get list of all changed file names.

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

# List all changed files (staged + unstaged + untracked), one per line.
# Usage: get_changed_files
get_changed_files() {
    { git diff HEAD --name-only 2>/dev/null
      git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u
}

# Show uncommitted changes. Default: stat only. Pass "full" for complete diffs.
# Usage: dump_diff        # stat + new file list
#        dump_diff full   # staged/unstaged diffs + new files
dump_diff() {
    local mode="${1:-stat}"
    local staged_stat unstaged_stat untracked

    staged_stat=$(git diff --cached --stat 2>/dev/null || true)
    unstaged_stat=$(git diff --stat 2>/dev/null || true)
    untracked=$(git ls-files --others --exclude-standard 2>/dev/null || true)

    if [ -z "$staged_stat" ] && [ -z "$unstaged_stat" ] && [ -z "$untracked" ]; then
        echo "## No Changes"
        echo "(no staged, unstaged, or untracked changes detected)"
        return
    fi

    if [ "$mode" = "full" ]; then
        if [ -n "$staged_stat" ]; then
            echo "## Staged Changes"
            echo "$staged_stat"
            echo ""
            echo "## Staged Diff"
            git diff --cached 2>/dev/null || true
        fi
        if [ -n "$unstaged_stat" ]; then
            echo ""
            echo "## Unstaged Changes"
            echo "$unstaged_stat"
            echo ""
            echo "## Unstaged Diff"
            git diff 2>/dev/null || true
        fi
    else
        echo "## Recent Changes"
        if [ -n "$staged_stat" ]; then
            echo "Staged:"
            echo "$staged_stat"
        fi
        if [ -n "$unstaged_stat" ]; then
            echo "Unstaged:"
            echo "$unstaged_stat"
        fi
    fi

    if [ -n "$untracked" ]; then
        echo ""
        echo "## New Files (untracked)"
        echo "$untracked"
    fi
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
    local count
    count=$(grep -cF "**Status:** $1" "$2" 2>/dev/null || true)
    echo "${count:-0}"
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
