#!/bin/bash
set -euo pipefail
# Preload for xp-plan-close: surface the five fields the close skill
# orchestrates against. TARGET_BRANCH is the primary integration branch
# — plan-close merges plan into primary, never plan into another plan,
# so we use get-primary directly (not get-target, which would return
# the plan branch when called from the plan branch itself).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-primary 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
# Route branch refs through emit_var for a uniform emit path across the close
# family (git refs can't forge a line, but keeping every emit consistent avoids
# reading as a gap). Shell vars stay raw for downstream use.
emit_var CURRENT_BRANCH "${CURRENT_BRANCH}"
emit_var TARGET_BRANCH "${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
# Threshold-gated full code review (shared Step 4b): emit CLOSE_CODE_FILE_COUNT
# + RUN_FULL_CODE_REVIEW for the cumulative close diff. Story-close omits this.
python3 "${PLUGIN_ROOT}/scripts/close_common.py" close-review-gate \
    --cwd . --target "${TARGET_BRANCH}" 2>/dev/null \
    || echo "RUN_FULL_CODE_REVIEW=false"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
echo "CLOSE_START_TS=$(now_iso)"
CLOSE_CYCLE_ID=$(generate_id)
echo "CLOSE_CYCLE_ID=${CLOSE_CYCLE_ID}"
emit_close_started_event plan "${CLOSE_CYCLE_ID}"
# Persist the id where a LATER process can read it. The echo above reaches the
# LLM only, and a concern raised mid-close is appended by a separate process —
# without the marker the merge gate is back to inferring which concerns belong
# to this close from the `files` they happened to record.
#
# write_marker ends in `2>/dev/null || true`, so a failed write is SILENT. That
# degrades safely rather than being guaranteed: no id on disk means no stamp,
# and an unstamped concern is still counted by the gate under the shipped
# files-relevance rule. It is never the reason a close fails to start.
write_marker CLOSE_CYCLE_ID "${CLOSE_CYCLE_ID}"
emit_system_context_rendered_for close-reviewer
# Arm the close-cycle Stop gate deterministically — prose-driven write
# was unreliable when the LLM skipped or reordered the invocation.
write_marker CLOSE_CYCLE_ACTIVE ""
emit_hook_guidance "$HOOK_STATUS"

# Append the close-pipeline reference so the LLM sees one consistent set of
# shared instructions instead of near-duplicate inlined copies.
#
# Two files, in this order. The review reference (Steps 4, 4b) is emitted only
# by the modes that RUN those steps — story-close defers both to its enclosing
# sprint-close, so it appends the shared file alone. Splitting the doc rather
# than filtering headings out of one keeps the mode scoping structural: a
# renamed heading cannot silently drop a section.
#
# Review file FIRST so Step 4 still precedes Step 5.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_review.md"
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
