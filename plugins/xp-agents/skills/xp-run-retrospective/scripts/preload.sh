#!/bin/bash
set -euo pipefail
# Preload for xp-retrospective: .retro-input.json content.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_guide

RETRO_INPUT="${SMM_DIR}/.retro-input.json"
if [ -f "$RETRO_INPUT" ]; then
    echo "## Retrospective Input Data"
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
# Drop raw events — digest has the structured version
data.pop('events_since_last_retro', None)
# Slim signal events: keep only type, content, short id
digest = data.get('digest', {})
if 'signal_events' in digest:
    digest['signal_events'] = [
        {'type': e.get('type',''), 'content': e.get('content',''), 'id': e.get('id','')[:8]}
        for e in digest['signal_events']
    ]
# Drop status samples — counts are sufficient
ss = digest.get('status_summary', {})
ss.pop('samples', None)
json.dump(data, sys.stdout, indent=2)
" "$RETRO_INPUT"
else
    echo "## Retrospective Data: no .retro-input.json found"
    echo "Insufficient data for retrospective."
fi
