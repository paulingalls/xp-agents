#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt for changed files.
# SMM is already in context (inline skill, not forked).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""
dump_diff

# Surface debt events for changed files
echo ""
echo "## Technical Debt for Changed Files"
changed_files=$(git diff HEAD~1 --name-only 2>/dev/null || true)
if [ -z "$changed_files" ]; then
    echo "(no changed files detected)"
else
    # shellcheck disable=SC2086
    python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/debt_for_files.py" \
        --smm-dir "$SMM_DIR" $changed_files 2>/dev/null || echo "(debt lookup unavailable)"
fi

# Surface unresolved plan review concerns
echo ""
echo "## Open Plan Review Concerns"
python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/open_plan_concerns.py" \
    --smm-dir "$SMM_DIR" 2>/dev/null || echo "(concern lookup unavailable)"
