#!/bin/bash
set -euo pipefail
# Preload for xp-run-sprint-retro: retro data + XP values + SMM pillars.
# Agent reads sprint.md directly via path in JSON.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Run prep script to build retro input
PREP_OUTPUT=$(python3 "$(dirname "$0")/prepare_sprint_retro_data.py" --smm-dir "$SMM_DIR" 2>&1)

echo "SMM_DIR=${SMM_DIR}"
# Only output RETRO_INPUT if prep script produced data
if echo "$PREP_OUTPUT" | grep -q "RETRO_INPUT="; then
    echo "$PREP_OUTPUT"
fi
echo ""

# XP values for analysis lenses
dump_values
echo ""

# Constraints + Wisdom pillars for evaluating sprint behavior
SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"
if [ -f "$SMM_FILE" ]; then
    echo "## SMM Constraints"
    smm_section "Constraints"
    echo ""
    echo "## SMM Wisdom"
    smm_section "Wisdom"
fi
