#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: surfaces marker headers the SKILL.md acts on.
# Prose explanations live in SKILL.md, not here — keep this lean.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

# Empty-body marker headers carry their action inline so they read like a
# directive rather than skimmable structure — visual heaviness is the
# load-bearing affordance for the consumer, not body content.
# (No RETRO_NEEDED marker: Step 1 is unconditional; the agent itself
# branches between populated and seed retros.)

if [ ! -f "$SYSTEM_CONTEXT_FILE" ] || [ -L "$SYSTEM_CONTEXT_FILE" ]; then
    echo "### NEEDS_SYSTEM_CONTEXT → invoke /xp-system-context"
    echo ""
fi

# Gate render_history on file presence so first-session kickoffs skip
# the Python cold-start cost; render_history.py owns the fail-quiet
# contract for malformed files.
if [ -f "${SMM_DIR}/session_history.json" ]; then
    python3 "$(dirname "$0")/render_history.py" --smm-dir "$SMM_DIR"
fi

if ! plan_has_remaining; then
    echo "### NEEDS_EXECUTION_PLAN → invoke /xp-plan"
    echo ""
fi

# Cache sprint_has_active — one python3 cold-start instead of two.
sprint_active=0
sprint_has_active && sprint_active=1

if [ -f "${SMM_DIR}/.needs-sprint" ] || [ "$sprint_active" -eq 0 ]; then
    echo "### NEEDS_SPRINT → invoke /xp-sprint-start"
    echo ""
fi

# Sprint status — surface counts + lists for any non-zero bucket.
if [ "$sprint_active" -eq 1 ]; then
    ready_count=0
    scheduled_count=0
    in_progress_count=0
    for kv in $(sprint_count); do
        case "$kv" in
            ready=*) ready_count=${kv#ready=} ;;
            scheduled=*) scheduled_count=${kv#scheduled=} ;;
            in-progress=*) in_progress_count=${kv#in-progress=} ;;
        esac
    done
    if [ "$ready_count" -gt 0 ] || [ "$scheduled_count" -gt 0 ] || [ "$in_progress_count" -gt 0 ]; then
        echo "### SPRINT_ACTIVE"
        echo "ready=${ready_count} scheduled=${scheduled_count} in-progress=${in_progress_count}"
        echo ""
        if [ "$ready_count" -gt 0 ]; then
            echo "Ready:"
            sprint_list_stories --status ready
            echo ""
        fi
        if [ "$scheduled_count" -gt 0 ]; then
            echo "Scheduled:"
            sprint_list_stories --status scheduled
            echo ""
        fi
        if [ "$in_progress_count" -gt 0 ]; then
            echo "In-progress:"
            sprint_list_stories --status in-progress
            echo ""
        fi
    fi
fi

# Orphan branches — SKILL.md drives the merge/keep/delete prompt.
ORPHAN_FREE=$(branching_list_free)
if [ -n "$ORPHAN_FREE" ]; then
    echo "### ORPHAN_FREE_BRANCHES"
    echo "$ORPHAN_FREE"
    echo ""
fi

ORPHAN_STORY=$(branching_list_story_orphans)
if [ -n "$ORPHAN_STORY" ]; then
    echo "### ORPHAN_STORY_BRANCHES"
    echo "$ORPHAN_STORY"
    echo ""
fi
