#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt + open plan concerns.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Auto-detect: when explicit TEAMMATE_CWD is unset AND orchestrator cwd is
# clean AND exactly one teammate worktree has uncommitted changes, route
# to that worktree. Orch-empty + single-match guards prevent hijacking
# orchestrator's own work or ambiguous multi-worktree cases.
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

echo ""
echo "## Debt for Changed Files"
changed_files=$(get_changed_files)
if [ -z "$changed_files" ]; then
    echo "(none)"
else
    # shellcheck disable=SC2086
    python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/debt_for_files.py" \
        --smm-dir "$SMM_DIR" $changed_files 2>/dev/null || echo "(lookup unavailable)"
fi

echo ""
echo "## Open Plan Concerns"
python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/open_plan_concerns.py" \
    --smm-dir "$SMM_DIR" 2>/dev/null || echo "(lookup unavailable)"
