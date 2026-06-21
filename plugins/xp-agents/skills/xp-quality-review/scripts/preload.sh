#!/bin/bash
set -euo pipefail
# Preload for xp-quality-review: changed files + debt + open plan concerns.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Auto-detect: when explicit TEAMMATE_CWD is unset, route to the worktree of
# the story actually being closed — the sprint-`closing` story. Quality-review
# runs at story-close Step 4.5b against that story, so its worktree is the
# correct review target. Keying on `closing` status (not "whichever worktree
# has uncommitted changes") prevents mis-targeting a different teammate that
# finished in the background. This mirrors story-close's own preload; the
# helper raises (non-zero) on two `closing` stories — a broken /xp-accept
# iteration — and `set -e` propagates it rather than guessing. Empty (no
# sprint / no closing story) → falls back to `.`.
_qr_auto_detect_teammate_cwd() {
    [ -n "${TEAMMATE_CWD:-}" ] && return 0   # explicit pass-through wins (798a27b425a7)
    local closing
    closing=$(find_closing_teammate_worktree)   # emits "<abs-path>\t<branch>"
    if [ -n "$closing" ]; then
        TEAMMATE_CWD="${closing%$'\t'*}"
        export TEAMMATE_CWD
    fi
}
_qr_auto_detect_teammate_cwd

echo "SMM_DIR=${SMM_DIR}"
echo "TEAMMATE_CWD=${TEAMMATE_CWD:-}"
echo ""

# Cadence-aware diff scope. Commit cadence reviews the staged/working diff
# (review runs before the commit). Story cadence relocates review to
# story-close, where the work is already committed — so review the cumulative
# range against the sprint-branch base instead (else the staged diff is empty
# and the reviewer sees nothing). REVIEW_BASE stays empty (→ staged fallback)
# unless cadence is 'story' AND a base resolves AND the committed range is
# non-empty (guards on-base / stage-0 / no-divergence).
REVIEW_BASE=""
CADENCE=$(_get_review_cadence)
if [ "$CADENCE" = "story" ]; then
    base=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "${SMM_DIR}" get-base --cwd "${TEAMMATE_CWD:-.}" 2>/dev/null || echo "")
    if [ -n "$base" ] && [ -n "$(get_changed_files_range "$base")" ]; then
        REVIEW_BASE="$base"
    fi
fi

if [ -n "$REVIEW_BASE" ]; then
    dump_diff_range "$REVIEW_BASE" full
    changed_files=$(get_changed_files_range "$REVIEW_BASE")
else
    dump_diff
    changed_files=$(get_changed_files)
fi

echo ""
echo "## Debt for Changed Files"
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
