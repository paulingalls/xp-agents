#!/bin/bash
set -euo pipefail
# Preload for xp-retrospective: .retro-input.json content.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

RETRO_INPUT="${SMM_DIR}/.retro-input.json"
if [ -f "$RETRO_INPUT" ]; then
    echo "## Retrospective Input Data"
    cat "$RETRO_INPUT"
else
    echo "## Retrospective Data: no .retro-input.json found"
    echo "Insufficient data for retrospective."
fi
