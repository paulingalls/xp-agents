#!/bin/bash
set -euo pipefail
# Preload for xp-story-close: surface the five fields the close skill
# orchestrates against. TARGET_BRANCH is the story base (sprint branch
# at stage 2+, primary otherwise) — story-close merges a story branch
# into its sprint base, never directly into a plan/primary branch
# during sprint execution.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-base --cwd . 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
echo "CURRENT_BRANCH=${CURRENT_BRANCH}"
echo "TARGET_BRANCH=${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
emit_hook_guidance "$HOOK_STATUS"
