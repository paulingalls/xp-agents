#!/bin/bash
set -euo pipefail
# Preload for xp-system-context: detect create vs update mode.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

CTX_FILE="${SMM_DIR}/system_context.md"

# Real file = update; symlink or missing = create
if [ -f "$CTX_FILE" ] && [ ! -L "$CTX_FILE" ]; then
    echo "MODE=update"
    echo "SYSTEM_CONTEXT=${CTX_FILE}"
else
    echo "MODE=create"
fi
