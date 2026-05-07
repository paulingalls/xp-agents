#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt for changed files.
# SMM is already in context (inline skill, not forked).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# TEAMMATE_CWD is set explicitly by the caller (e.g., /xp-accept's
# fix-cycle dispatch) when quality-review should grab a teammate
# worktree's diff. Empty/unset means use the orchestrator's cwd.
# (Story-004 removed the ACCEPT_ACTIVE-gated auto-detect that used to
# infer this from sprint state — the heuristic could hijack the
# orchestrator's diff when a teammate sat in `reviewing` for unrelated
# work. Per decision 798a27b425a7: explicit pass-through only.)

echo "SMM_DIR=${SMM_DIR}"
echo "TEAMMATE_CWD=${TEAMMATE_CWD:-}"
echo ""
dump_diff

# Surface debt events for changed files
echo ""
echo "## Technical Debt and Concerns for Changed Files"
changed_files=$(get_changed_files)
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
