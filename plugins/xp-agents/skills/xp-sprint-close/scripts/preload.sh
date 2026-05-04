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
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
echo "CLOSE_START_TS=$(now_iso)"
echo "CLOSE_CYCLE_ID=$(generate_id)"
emit_hook_guidance "$HOOK_STATUS"

# End-of-flow safety net: clear any ACCEPT_ACTIVE marker so it cannot
# persist across sprint boundaries and block pre_tool_write re-arming
# of `.accept` in the next session. Idempotent — no-op when absent.
consume_marker ACCEPT_ACTIVE

# Append shared close-pipeline reference (Steps 5, 5b, 6) so the LLM
# sees one consistent set of shared instructions across all four close
# skills instead of four near-duplicate inlined copies.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
