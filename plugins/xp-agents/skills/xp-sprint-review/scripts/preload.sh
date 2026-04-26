#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-review: prepare review data, output paths.
# Agent reads sprint.json and execution_plan.md directly via paths in JSON.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Per-invocation tempfile so concurrent sprint-review preloads in
# different worktrees never race on a shared path. Cleaned up by
# _preload_base.sh's stale-tempfile sweep on the next preload AND by
# subagent_stop after the reviewer finishes.
REVIEW_INPUT=$(mktemp "${SMM_DIR}/.sprint-review-input.XXXXXX")
PREP_OUTPUT=$(python3 "$(dirname "$0")/prepare_review_data.py" \
    --smm-dir "$SMM_DIR" --target "$REVIEW_INPUT" 2>&1)

echo "SMM_DIR=${SMM_DIR}"
# Only output REVIEW_INPUT when prep script produced data; remove the
# empty mktemp file otherwise so it doesn't pollute SMM_DIR.
if echo "$PREP_OUTPUT" | grep -q "REVIEW_INPUT="; then
    echo "$PREP_OUTPUT"
else
    rm -f "$REVIEW_INPUT"
fi
