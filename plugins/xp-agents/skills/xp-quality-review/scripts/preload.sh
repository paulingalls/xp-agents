#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt for changed files.
# SMM is already in context (inline skill, not forked).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# TEAMMATE_CWD is set explicitly by the caller (e.g., /xp-accept's
# fix-cycle dispatch) when quality-review should grab a teammate
# worktree's diff. Explicit pass-through always wins (per decision
# 798a27b425a7).
#
# When unset, narrow auto-detect: route to a teammate worktree ONLY
# when the orchestrator cwd has zero uncommitted changes AND exactly
# one teammate worktree has uncommitted changes. The orch-empty trigger
# is the hijack guard — an orchestrator with its own in-flight work is
# never overridden. Single-match avoids ambiguity. Closes the gap where
# the orchestrator edited a teammate worktree directly (close-cycle fix
# pass) and QR silently reported "no changed files".
_qr_auto_detect_teammate_cwd() {
    [ -n "${TEAMMATE_CWD:-}" ] && return 0
    if ! git diff --quiet HEAD 2>/dev/null \
       || [ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]; then
        return 0
    fi
    local matches=()
    while IFS= read -r wt; do
        [ -z "$wt" ] && continue
        if ! git -C "$wt" diff --quiet HEAD 2>/dev/null \
           || [ -n "$(git -C "$wt" ls-files --others --exclude-standard 2>/dev/null)" ]; then
            matches+=("$wt")
        fi
    done < <(git worktree list --porcelain 2>/dev/null \
             | awk '/^worktree / { if ($2 ~ /\/\.claude\/worktrees\/worktree-story-/) print $2 }')
    if [ "${#matches[@]}" -eq 1 ]; then
        TEAMMATE_CWD="${matches[0]}"
        export TEAMMATE_CWD
    fi
}
_qr_auto_detect_teammate_cwd

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
