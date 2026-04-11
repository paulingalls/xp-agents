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
    if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
        echo "## Current SMM State"
        python3 "${PLUGIN_ROOT}/smm/smm_view.py" dump --smm-dir "$SMM_DIR" 2>/dev/null
    else
        echo "## SMM State: no materialized view"
    fi
}

smm_render_to_tempfile() {
    # Unique tempfile per call — concurrent preloads must not race on a shared path.
    # BSD mktemp (macOS) requires the X's at the end of the template, so no suffix.
    # Agents Read the file via the Read tool, which is extension-agnostic.
    local out
    out=$(mktemp "${SMM_DIR}/.smm-rendered.XXXXXX")
    python3 "${PLUGIN_ROOT}/smm/smm_view.py" dump --smm-dir "$SMM_DIR" > "$out" 2>/dev/null
    echo "$out"
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

smm_has_section() {
    python3 "${PLUGIN_ROOT}/smm/smm_view.py" has-section "$1" --smm-dir "$SMM_DIR" 2>/dev/null
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

smm_section() {
    local name="$1"
    python3 "${PLUGIN_ROOT}/smm/smm_view.py" section "$name" --smm-dir "$SMM_DIR" 2>/dev/null
}

# Output SYSTEM_CONTEXT=<path> if system_context.md exists (not a symlink).
check_system_context() {
    local ctx="${SMM_DIR}/system_context.md"
    if [ -f "$ctx" ] && [ ! -L "$ctx" ]; then
        echo ""
        echo "SYSTEM_CONTEXT=${ctx}"
    fi
}

# Execution plan CLI helpers (thin wrappers over plan_cli.py).
plan_exists() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" exists 2>/dev/null
}

plan_has_remaining() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" has-remaining 2>/dev/null
}

plan_count() {
    python3 "${PLUGIN_ROOT}/smm/plan_cli.py" --smm-dir "$SMM_DIR" count 2>/dev/null
}
