#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-close: surface the five fields the close skill
# orchestrates against (current/target branch, gh availability, dirty
# state).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-target --cwd . 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
echo "CURRENT_BRANCH=${CURRENT_BRANCH}"
echo "TARGET_BRANCH=${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
# Threshold-gated full code review (shared Step 4b): emit CLOSE_CODE_FILE_COUNT
# + RUN_FULL_CODE_REVIEW for the cumulative close diff. Story-close omits this.
python3 "${PLUGIN_ROOT}/scripts/close_common.py" close-review-gate \
    --cwd . --target "${TARGET_BRANCH}" 2>/dev/null \
    || echo "RUN_FULL_CODE_REVIEW=false"

# Verify-acceptance gate signal (M6): the last sprint-verify rerun's status.
# Exit 1 (red) is a gate signal, not an error — keep the preload green and
# default an empty/error read to "none" (no gate when no sprint/event exists).
VERIFY_STATUS=$(python3 "${PLUGIN_ROOT}/scripts/verify_acceptance.py" \
    --query-verify-status --smm-dir "${SMM_DIR}" 2>/dev/null | head -1) || true
echo "VERIFY_STATUS=${VERIFY_STATUS:-none}"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
echo "CLOSE_START_TS=$(now_iso)"
CLOSE_CYCLE_ID=$(generate_id)
echo "CLOSE_CYCLE_ID=${CLOSE_CYCLE_ID}"
emit_close_started_event sprint "${CLOSE_CYCLE_ID}"
emit_system_context_rendered_for close-reviewer
# Arm the close-cycle Stop gate deterministically — prose-driven write
# was unreliable when the LLM skipped or reordered the invocation.
write_marker CLOSE_CYCLE_ACTIVE ""
emit_hook_guidance "$HOOK_STATUS"

# Append shared close-pipeline reference (Steps 5, 5b, 6) so the LLM
# sees one consistent set of shared instructions across all four close
# skills instead of four near-duplicate inlined copies.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
