#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-review: prepare review data, output paths.
# Agent reads sprint.md and execution_plan.md directly via paths in JSON.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Run prep script to build review input
PREP_OUTPUT=$(python3 "$(dirname "$0")/prepare_review_data.py" --smm-dir "$SMM_DIR" 2>&1)

echo "SMM_DIR=${SMM_DIR}"
# Only output REVIEW_INPUT if prep script produced data
if echo "$PREP_OUTPUT" | grep -q "REVIEW_INPUT="; then
    echo "$PREP_OUTPUT"
fi
