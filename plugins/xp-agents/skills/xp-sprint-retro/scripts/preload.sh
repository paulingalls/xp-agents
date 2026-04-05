#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-retro: prepare retro data, output paths.
# SMM, sprint, and guide are injected by SubagentStart.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Run prep script to build retro input
PREP_OUTPUT=$(python3 "$(dirname "$0")/prepare_sprint_retro_data.py" --smm-dir "$SMM_DIR" 2>&1)

echo "SMM_DIR=${SMM_DIR}"
# Only output RETRO_INPUT if prep script produced data
if echo "$PREP_OUTPUT" | grep -q "RETRO_INPUT="; then
    echo "$PREP_OUTPUT"
fi
