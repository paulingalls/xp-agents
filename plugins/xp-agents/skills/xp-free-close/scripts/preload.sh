#!/bin/bash
set -euo pipefail
# Preload for xp-free-close: surface the six fields the close skill
# orchestrates against. TARGET_BRANCH is the primary integration branch
# — free-close merges a free branch into primary, never into a plan
# branch, so we use get-primary directly (not get-target, which would
# return a recorded plan branch when one is set in execution_plan.json).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-primary 2>/dev/null || echo "")

# Per-invocation tempfile so concurrent close skills in different worktrees
# never race on a shared path. The close-reviewer subagent receives this
# path explicitly through the Agent prompt — no SubagentStart injection.
# Cleaned up by _preload_base.sh's stale-tempfile sweep on the next preload.
REVIEW_INPUT=$(mktemp "${SMM_DIR}/.close-review-input.XXXXXX")

echo "SMM_DIR=${SMM_DIR}"
echo "CURRENT_BRANCH=${CURRENT_BRANCH}"
echo "TARGET_BRANCH=${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
echo "REVIEW_INPUT=${REVIEW_INPUT}"
