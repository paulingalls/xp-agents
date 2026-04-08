#!/bin/bash
set -euo pipefail
# Preload for xp-run-sprint-retro: retro data + SMM path.
# Agent reads sprint.md directly via path in JSON.
# Agent reads SMM file for Constraints/Wisdom via Read tool.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

RETRO_INPUT_FILE="${SMM_DIR}/.sprint-retro-input.json"
if [ -f "$RETRO_INPUT_FILE" ]; then
    # Idempotent: SessionStart hook or a prior run already prepared the
    # input file. Don't recompute — just emit the path.
    echo "RETRO_INPUT=${RETRO_INPUT_FILE}"
else
    PREP_SCRIPT="${PLUGIN_ROOT}/scripts/prepare_sprint_retro_data.py"
    PREP_OUTPUT=$(python3 "$PREP_SCRIPT" --smm-dir "$SMM_DIR" 2>&1)
    if echo "$PREP_OUTPUT" | grep -q "RETRO_INPUT="; then
        echo "$PREP_OUTPUT"
    fi
fi

# SMM file path (agent reads Constraints + Wisdom via Read tool)
SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
if [ -f "$SMM_FILE" ]; then
    echo "SMM_FILE=${SMM_FILE}"
fi
