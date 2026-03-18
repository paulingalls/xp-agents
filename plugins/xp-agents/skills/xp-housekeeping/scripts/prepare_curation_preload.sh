#!/bin/bash
set -euo pipefail
# Preload for xp-housekeeping (M2): output existing SMM + structured curation data.
# Does NOT source _preload_base.sh to avoid overwriting a curated four-pillar SMM.

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SMM_DIR=$("${PLUGIN_ROOT}/smm/init.sh" 2>/dev/null) || {
    echo "## Curation Data: unavailable"
    exit 0
}

# Only materialize if no curated SMM exists yet (first-ever curation)
if [ ! -f "${SMM_DIR}/.curation-watermark" ]; then
    python3 "${PLUGIN_ROOT}/smm/materialize.py" >/dev/null 2>&1 || true
fi

echo "## Existing SMM"
echo ""
if [ -f "${SMM_DIR}/SHARED_MENTAL_MODEL.md" ]; then
    cat "${SMM_DIR}/SHARED_MENTAL_MODEL.md"
else
    echo "(no existing SMM — first curation)"
fi
echo ""
echo "---"
echo ""
echo "## Curation Data (JSON)"
echo ""
python3 "${PLUGIN_ROOT}/skills/xp-housekeeping/scripts/prepare_curation.py" --smm-dir "${SMM_DIR}" || echo '{"error": "prepare_curation.py failed"}'
echo ""
echo "## SMM_DIR"
echo "${SMM_DIR}"
