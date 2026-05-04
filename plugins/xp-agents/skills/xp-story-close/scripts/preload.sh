#!/bin/bash
set -euo pipefail
# Preload for xp-story-close: surface the five fields the close skill
# orchestrates against. TARGET_BRANCH is the story base (sprint branch
# at stage 2+, primary otherwise) — story-close merges a story branch
# into its sprint base, never directly into a plan/primary branch
# during sprint execution.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Implicit teammate-worktree discovery (story-002 sprint-057): when
# /xp-accept dispatches /xp-story-close after marking a teammate story
# done, the orchestrator sits on the SPRINT branch — not the story
# branch. Pair the live teammate worktree against sprint.json status
# to discover the worktree of the just-done story; emit TEAMMATE_CWD
# + override CURRENT_BRANCH from the worktree's HEAD. Empty TEAMMATE_CWD
# means solo flow (orchestrator IS on the story branch).
#
# Multi-match (two `done` stories with live worktrees) signals broken
# /xp-accept iteration — surface the helper's stderr and propagate the
# non-zero exit (set -e) rather than masking it as solo flow. The
# helper's "fail loud" contract only holds if its callers don't swallow.
CLOSING=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" find-closing-teammate-worktree --cwd .)
if [ -n "$CLOSING" ]; then
    TEAMMATE_CWD="${CLOSING% *}"
    CURRENT_BRANCH="${CLOSING##* }"
else
    TEAMMATE_CWD=""
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-base --cwd . 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
echo "TEAMMATE_CWD=${TEAMMATE_CWD}"
echo "CURRENT_BRANCH=${CURRENT_BRANCH}"
echo "TARGET_BRANCH=${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
echo "TEST_COMMAND=$(find_test_command)"
echo "CLOSE_START_TS=$(now_iso)"
echo "CLOSE_CYCLE_ID=$(generate_id)"
emit_hook_guidance "$HOOK_STATUS"

clear_accept_active_marker

# Append shared close-pipeline reference (Steps 5, 5b, 6) so the LLM
# sees one consistent set of shared instructions across all four close
# skills instead of four near-duplicate inlined copies.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
