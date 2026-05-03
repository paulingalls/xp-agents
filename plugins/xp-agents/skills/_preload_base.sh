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

# Clean up temp files from previous preload runs.
# These are created by smm_render_to_tempfile/sprint_render_to_tempfile
# and are safe to remove once the previous skill has finished.
find "$SMM_DIR" -maxdepth 1 \( -name ".smm-rendered.*" -o -name ".sprint-rendered.*" -o -name ".sprint-review-input.*" \) -exec rm -f {} + 2>/dev/null || true

dump_smm() {
    if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
        echo "## Current SMM State"
        python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" render 2>/dev/null
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
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" render > "$out" 2>/dev/null
    echo "$out"
}

sprint_render_to_tempfile() {
    local out
    out=$(mktemp "${SMM_DIR}/.sprint-rendered.XXXXXX")
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" render > "$out" 2>/dev/null
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

# Echo "true" if the working tree has no staged/unstaged changes, else "false".
# Usage: worktree_clean
worktree_clean() {
    if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
        echo "true"
    else
        echo "false"
    fi
}

# Echo "true" if the gh CLI is on PATH, else "false". Uses the POSIX
# command -v builtin instead of `which` (no extra subprocess).
# Usage: gh_available
gh_available() {
    if command -v gh >/dev/null 2>&1; then
        echo "true"
    else
        echo "false"
    fi
}

# Echo "present" or "absent" — does the project run tests via a git
# hook on commit or push? Used by the close-skill preloads to drive
# the hook-absent fallback prose. Falls through to "absent" if the
# helper is missing or python3 is unavailable.
# Usage: pre_commit_hook_present
pre_commit_hook_present() {
    python3 "${PLUGIN_ROOT}/scripts/close_common.py" \
        hook-present --cwd . 2>/dev/null || echo "absent"
}

# Print current UTC time in ISO 8601 format matching events.jsonl's
# `ts` field shape ("YYYY-MM-DDTHH:MM:SS.ffffff+00:00"). Used by
# close-skill preloads to capture CLOSE_START_TS for the Step 6
# auto-merge gate's `count-classifications --since-ts` bound. Python
# (not `date`) for portability — `date -u --iso-8601=seconds` is
# GNU-only; macOS BSD `date` rejects the long flag form.
#
# Mirrors smm/_append_impl.py:now_iso() (the source-of-truth used
# by append.sh when stamping events.jsonl entries). This shell
# variant exists because preload.sh runs before any Python module
# is imported; calling _append_impl directly would force preload to
# set up sys.path. Lexicographic comparison against event ts values
# is safe because both sides use the same fixed-width zero-padded
# fields produced by datetime.isoformat().
#
# Usage: now_iso
now_iso() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())"
}

# Generate a 12-char hex ID matching event_builder.generate_id() shape.
# Used by close-skill preloads to capture CLOSE_CYCLE_ID — the strict
# scoper for the Step 6 auto-merge gate's count-classifications query.
# Cycle-id (not just since-ts) prevents concurrent close-cycles in
# other teammate worktrees from leaking concern_classify events into
# this cycle's count.
#
# Usage: generate_id
generate_id() {
    python3 -c "import secrets; print(secrets.token_hex(6))"
}

# Look up the project's test command from system_context.stack.test_command.
# Returns the value (e.g. "pytest -n auto", "npm test", "cargo test")
# or empty string when unset / system_context.json missing.
#
# Used by the story-close + free-close auto-merge override (Step 6) to
# decide whether to fire a deterministic test gate before merging.
# Empty result means "no test command configured" — the override falls
# through to the confirm prompt rather than guessing a project-specific
# command (the plugin ships to repos that may use any test runner or
# none at all).
#
# Wraps `system_context_cli.py get-stack-field test_command`, mirroring
# the `pre_commit_hook_present` pattern of delegating to the
# corresponding CLI rather than inlining Python in shell.
#
# To enable the auto-merge gate in your project, set the field via:
#     printf %s '"<your test command>"' | python3 \
#         "${PLUGIN_ROOT}/smm/system_context_cli.py" --smm-dir "$SMM_DIR" \
#         edit-stack-field test_command
# (or let /xp-system-context's analyzer detect it from your project's
# package.json / pyproject.toml / Cargo.toml / etc. — see Step 3.7
# of agents/xp-system-analyzer.md).
#
# Usage: find_test_command
find_test_command() {
    python3 "${PLUGIN_ROOT}/smm/system_context_cli.py" \
        --smm-dir "${SMM_DIR}" get-stack-field test_command 2>/dev/null \
        || echo ""
}

# Conditionally emit a HOOK_GUIDANCE section when no hook will fire on
# the close skill's merge. Single source of truth — replaces 4 copies
# of identical prose previously inlined in each close skill's SKILL.md.
# Usage: emit_hook_guidance "$(pre_commit_hook_present)"
emit_hook_guidance() {
    if [ "$1" = "absent" ]; then
        echo ""
        echo "### HOOK_GUIDANCE"
        echo "PRE_COMMIT_HOOK=absent — the merge in Step 7 won't fire"
        echo "any project tests. Before confirming the merge, run the"
        echo "project's test command (look in CLAUDE.md) so the merged"
        echo "state is verified."
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
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" has-section "$1" 2>/dev/null
}

# Find the latest retrospective JSON file.
# Usage: get_latest_retro "$RETRO_DIR"
# Returns path on stdout, empty string if none found.
get_latest_retro() {
    find "$1" -maxdepth 1 -name "*.json" 2>/dev/null | sort -r | head -1
}

# Extract Try items from a retrospective JSON file.
# Usage: get_try_items "$RETRO_FILE"
# Outputs "- <content> [refs: <id1>, ...]" lines when event_refs present.
get_try_items() {
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
items = data.get('try', [])
statuses = data.get('try_status', [])
for i, item in enumerate(items):
    if i < len(statuses) and statuses[i].get('resolved_this_session'):
        continue
    c = item.get('content', item) if isinstance(item, dict) else item
    refs = list(item.get('event_refs', [])) if isinstance(item, dict) else []
    own_id = item.get('id', '') if isinstance(item, dict) else ''
    if own_id:
        refs.insert(0, own_id)
    if refs:
        print(f'- {c} [refs: {\", \".join(refs)}]')
    else:
        print(f'- {c}')
" "$1" 2>/dev/null || true
}

# Sprint CLI helpers (thin wrappers over sprint_cli.py).
sprint_exists() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" exists 2>/dev/null
}

sprint_has_active() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" has-active 2>/dev/null
}

# Count stories with a specific status. Returns a single number.
# Usage: sprint_count_status ready
sprint_count_status() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" count-status "$1" 2>/dev/null || echo "0"
}

# List stories, optionally filtered by status.
# Usage: sprint_list_stories [--status ready]
sprint_list_stories() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" list-stories "$@" 2>/dev/null
}

# Next sprint ID (increments current, falls back to sprint-001).
sprint_next_id() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" next-id 2>/dev/null || echo "sprint-001"
}

sprint_count() {
    python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "$SMM_DIR" count 2>/dev/null
}

smm_section() {
    local name="$1"
    python3 "${PLUGIN_ROOT}/smm/smm_cli.py" --smm-dir "$SMM_DIR" section "$name" 2>/dev/null
}

# Canonical filename — single source of truth for shell scripts.
SYSTEM_CONTEXT_FILE="${SMM_DIR}/system_context.json"

# Output SYSTEM_CONTEXT=<path> if system_context.json exists (not a symlink).
check_system_context() {
    local ctx="${SYSTEM_CONTEXT_FILE}"
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

# Branching CLI helpers (thin wrappers over scripts/branching.py).
# List the user's free branches, excluding HEAD. One branch per line.
# Usage: branching_list_free
branching_list_free() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "$SMM_DIR" list-free --cwd . 2>/dev/null
}

# List orphan story branches (story branches not backed by active stories).
# Usage: branching_list_story_orphans
branching_list_story_orphans() {
    python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "$SMM_DIR" list-story-orphans --cwd . 2>/dev/null
}

# Marker helpers (thin wrappers over markers.py).
# Usage: consume_marker ACCEPT
#        write_marker NEEDS_HOUSEKEEPING "kickoff"
#
# Values are passed via sys.argv so content with quotes/backslashes is safe.
consume_marker() {
    local marker_name="$1"
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
markers.marker_consume(Path(sys.argv[3]), getattr(markers, sys.argv[4]))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "${marker_name}" 2>/dev/null || true
}

write_marker() {
    local marker_name="$1"
    local content="$2"
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
markers.marker_write(Path(sys.argv[3]), getattr(markers, sys.argv[4]), sys.argv[5])
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "${marker_name}" "${content}" 2>/dev/null || true
}
