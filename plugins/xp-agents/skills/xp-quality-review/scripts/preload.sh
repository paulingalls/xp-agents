#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt for changed files.
# SMM is already in context (inline skill, not forked).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

dump_diff

# Surface debt events for changed files
echo ""
echo "## Technical Debt for Changed Files"
mapfile -t changed_files < <(git diff HEAD~1 --name-only 2>/dev/null || true)
if [ ${#changed_files[@]} -eq 0 ]; then
    echo "(no changed files detected)"
else
    python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/debt_for_files.py" \
        --smm-dir "$SMM_DIR" "${changed_files[@]}" 2>/dev/null || echo "(debt lookup unavailable)"
fi
