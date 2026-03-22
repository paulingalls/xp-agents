#!/bin/bash
set -euo pipefail
# Preload for xp-question-triage: check for open questions and intents.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""
SMM_FILE="${SMM_DIR}/SHARED_MENTAL_MODEL.md"

# Open questions live in the Risks pillar
if [ -f "$SMM_FILE" ] && smm_has_section "Risks"; then
    echo "### Open Questions:"
    smm_section "Risks" 30 | head -20
else
    echo "### Open Questions: none"
fi

echo ""

# Customer intent lives in the Intent pillar
if [ -f "$SMM_FILE" ] && smm_has_section "Intent"; then
    echo "### Customer Intent:"
    smm_section "Intent" 30 | head -20
else
    echo "### Customer Intent: none tracked"
fi

echo ""

# Previous Try items from latest retrospective
RETRO_DIR="${SMM_DIR}/retrospectives"
echo "### Previous Try Items:"
if [ -d "$RETRO_DIR" ]; then
    LATEST_RETRO=$(find "$RETRO_DIR" -maxdepth 1 -name "*.json" 2>/dev/null | sort -r | head -1)
    if [ -n "$LATEST_RETRO" ]; then
        python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
tries = data.get('try', [])
if tries:
    for t in tries:
        content = t.get('content', t) if isinstance(t, dict) else t
        print(f'- {content}')
else:
    print('(none)')
" "$LATEST_RETRO" 2>/dev/null || echo "(could not read retro file)"
    else
        echo "(no previous retrospective)"
    fi
else
    echo "(none)"
fi
