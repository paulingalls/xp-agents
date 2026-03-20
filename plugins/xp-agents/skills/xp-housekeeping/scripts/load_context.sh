#!/bin/bash
set -euo pipefail
# Outputs SMM_FILE and GUIDE_FILE paths for the housekeeping skill to Read.
# Usage: load_context.sh [SMM_DIR]
# Pass SMM_DIR from preload output to avoid init.sh env var issues.

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if [ -n "${1:-}" ]; then
    SMM_DIR="$1"
else
    SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
        echo "SMM unavailable" >&2
        exit 0
    }
fi

echo "SMM_FILE=${SMM_DIR}/SHARED_MENTAL_MODEL.md"
echo "GUIDE_FILE=${PLUGIN_ROOT}/BEHAVIORAL_GUIDE.md"
