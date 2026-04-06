#!/bin/bash
set -euo pipefail
# Preload for xp-housekeeping (forked): prepare curation data, output paths + guide.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Create .curation-input.json by redirecting existing prepare_curation.py
SCRIPT_DIR="$(dirname "$0")"
python3 "${SCRIPT_DIR}/prepare_curation.py" --smm-dir "$SMM_DIR" \
    > "${SMM_DIR}/.curation-input.json" 2>/dev/null || true

echo "SMM_DIR=${SMM_DIR}"
if [ -f "${SMM_DIR}/.curation-input.json" ]; then
    echo "CURATION_INPUT=${SMM_DIR}/.curation-input.json"
fi
echo ""

dump_guide
