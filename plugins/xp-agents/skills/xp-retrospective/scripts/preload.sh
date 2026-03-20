#!/bin/bash
set -euo pipefail
# Preload for xp-retrospective: .retro-input.json content.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

RETRO_INPUT="${SMM_DIR}/.retro-input.json"
if [ -f "$RETRO_INPUT" ]; then
    echo "## Retrospective Input Data"
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
data.pop('events_since_last_retro', None)
json.dump(data, sys.stdout, indent=2)
" "$RETRO_INPUT"
else
    echo "## Retrospective Data: no .retro-input.json found"
    echo "Insufficient data for retrospective."
fi
