#!/bin/bash
set -euo pipefail
# Preload for xp-kickoff: determine what session-start work is needed.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

RETRO_INPUT="${SMM_DIR}/.retro-input.json"

echo "SMM_DIR=${SMM_DIR}"
echo ""
echo "## Session Review Status"
echo ""

# 1. Check for retrospective data. Sprint sizing is now included in the
# session retro input — no separate sprint retro path.
if [ -f "$RETRO_INPUT" ]; then
    echo "### RETRO_NEEDED"
    echo "Unanalyzed events from previous session found."
    echo ""
fi

# 2. Check for system context
if [ ! -f "$SYSTEM_CONTEXT_FILE" ] || [ -L "$SYSTEM_CONTEXT_FILE" ]; then
    echo "### NEEDS_SYSTEM_CONTEXT"
    echo "No system_context.json found. Run /xp-system-context to create one."
    echo ""
fi

# 2.5. Render last-session history. Gate the subprocess on file presence
# so first-session and abandoned-history kickoffs don't pay the Python
# cold-start cost; render_history.py still owns the fail-quiet contract
# for the corrupt-file path.
if [ -f "${SMM_DIR}/session_history.json" ]; then
    python3 "$(dirname "$0")/render_history.py" --smm-dir "$SMM_DIR"
fi

# 3. Check for execution plan (JSON format, via CLI)
if ! plan_has_remaining; then
    echo "### NEEDS_EXECUTION_PLAN"
    echo "No execution plan with remaining work. Run /xp-plan to create one."
    echo ""
fi

# 4. Check for sprint (marker OR no active stories)
if [ -f "${SMM_DIR}/.needs-sprint" ]; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
elif ! sprint_has_active; then
    echo "### NEEDS_SPRINT"
    echo "No active sprint. Run /xp-sprint-start to plan a sprint."
    echo ""
fi

# 5. Sprint status (for work selection context)
in_progress_count=0
if sprint_has_active; then
    # One subprocess call gets all status counts; pure-bash parse
    # avoids per-status subprocess spawns and drift risk if a future
    # status renames/reorders.
    ready_count=0
    scheduled_count=0
    for kv in $(sprint_count); do
        case "$kv" in
            ready=*) ready_count=${kv#ready=} ;;
            scheduled=*) scheduled_count=${kv#scheduled=} ;;
            in-progress=*) in_progress_count=${kv#in-progress=} ;;
        esac
    done
    if [ "$ready_count" -gt 0 ] || [ "$scheduled_count" -gt 0 ] || [ "$in_progress_count" -gt 0 ]; then
        echo "### SPRINT_ACTIVE"
        echo "Sprint counts: ready=${ready_count} scheduled=${scheduled_count} in-progress=${in_progress_count}"
        echo ""
        if [ "$ready_count" -gt 0 ]; then
            echo "Ready stories:"
            sprint_list_stories --status ready
            echo ""
        fi
        if [ "$scheduled_count" -gt 0 ]; then
            echo "Scheduled stories (queued by xp-work-selection, awaiting xp-assign branch creation):"
            sprint_list_stories --status scheduled
            echo ""
        fi
        if [ "$in_progress_count" -gt 0 ]; then
            echo "In-progress stories (branch exists, work underway):"
            sprint_list_stories --status in-progress
            echo ""
        fi
    fi
fi

# 6. Orphan free branches — surface unfinished free work for the user
# to merge/keep/delete at every kickoff (regardless of session mode).
ORPHAN_FREE=$(branching_list_free)
if [ -n "$ORPHAN_FREE" ]; then
    echo "### ORPHAN_FREE_BRANCHES"
    echo "Unfinished free branches detected. Per branch, ask merge/keep/delete."
    echo ""
    echo "$ORPHAN_FREE"
    echo ""
fi

# 7. Orphan story branches — story branches not backed by active sprint stories.
ORPHAN_STORY=$(branching_list_story_orphans)
if [ -n "$ORPHAN_STORY" ]; then
    echo "### ORPHAN_STORY_BRANCHES"
    echo "Orphan story branches detected. Per branch, ask merge/keep/delete."
    echo ""
    echo "$ORPHAN_STORY"
    echo ""
fi

# .needs-kickoff is cleared by kickoff_gate.py (UserPromptSubmit hook)
# which runs before this preload. The .needs-housekeeping marker is
# written later by the xp-work-selection preload (step 5) so the stop
# gate doesn't block during earlier kickoff steps.
