#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-review: prep review data, emit paths.
# Per-invocation tempfile prevents concurrent-worktree races on a shared path.
# Cleaned by _preload_base.sh's stale-tempfile sweep + subagent_stop.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

REVIEW_INPUT=$(mktemp "${SMM_DIR}/.sprint-review-input.XXXXXX")
PREP_OUTPUT=$(python3 "$(dirname "$0")/prepare_review_data.py" \
    --smm-dir "$SMM_DIR" --target "$REVIEW_INPUT" 2>&1)

echo "SMM_DIR=${SMM_DIR}"
if echo "$PREP_OUTPUT" | grep -q "REVIEW_INPUT="; then
    echo "$PREP_OUTPUT"
else
    rm -f "$REVIEW_INPUT"
fi
