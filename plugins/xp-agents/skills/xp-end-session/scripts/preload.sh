#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/../../_preload_base.sh"

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "SMM_DIR=${SMM_DIR}"
echo ""

python3 "${SKILL_DIR}/scripts/format_preload.py" --smm-dir "${SMM_DIR}"
