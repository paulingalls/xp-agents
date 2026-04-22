#!/bin/bash
set -euo pipefail
# Preload for xp-system-context: detect create vs update mode.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Real file = update; symlink or missing = create
if [ -f "$SYSTEM_CONTEXT_FILE" ] && [ ! -L "$SYSTEM_CONTEXT_FILE" ]; then
    echo "MODE=update"
    echo "SYSTEM_CONTEXT=${SYSTEM_CONTEXT_FILE}"
else
    echo "MODE=create"
fi
