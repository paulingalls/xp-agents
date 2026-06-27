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
# MODE discriminator: a fresh /code-review this cycle (simplify_done set for the
# review target's agent_id) => consume-findings; else => self-find. Resolved
# from TEAMMATE_CWD (the closing-story worktree, else the main checkout) so the
# read keys match the per-commit gate's writer. Defaults to self-find on error.
MODE=$(python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/review_mode.py" \
    --smm-dir "$SMM_DIR" --cwd "${TEAMMATE_CWD:-.}" 2>/dev/null || echo "self-find")
echo "MODE=${MODE}"
echo ""

# Diff scope. Default: the staged/working diff (review runs before the commit).
# Two cases relocate review to a committed range because the work is already
# committed by the time the review runs — else the staged diff is empty and the
# reviewer sees nothing. Both reuse REVIEW_BASE + the dump_diff_range plumbing
# below; precedence is explicit:
#
#   1. MODE=consume-findings (free/sprint/plan close, per the v3.10.0 role
#      split — story-close + per-increment are self-find, never consume). The
#      close diff is already committed, so review TARGET...HEAD against the
#      merge target. This is checked FIRST: a close is not story cadence, so
#      the two never collide, but consume-findings is the more specific signal.
#   2. else CADENCE=story (story-close Step 4.5b): review BASE...HEAD against
#      the sprint-branch base.
#
# REVIEW_BASE stays empty (→ working-tree fallback) unless a ref resolves AND
# its committed range is non-empty (guards on-target/on-base, stage-0, and
# no-divergence — symmetric to the story branch).
REVIEW_BASE=""
CADENCE=$(_get_review_cadence)
if [ "$MODE" = "consume-findings" ]; then
    target=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "${SMM_DIR}" get-target --cwd "${TEAMMATE_CWD:-.}" 2>/dev/null || echo "")
    if [ -n "$target" ] && [ -n "$(get_changed_files_range "$target")" ]; then
        REVIEW_BASE="$target"
    fi
elif [ "$CADENCE" = "story" ]; then
    base=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
        --smm-dir "${SMM_DIR}" get-base --cwd "${TEAMMATE_CWD:-.}" 2>/dev/null || echo "")
    if [ -n "$base" ] && [ -n "$(get_changed_files_range "$base")" ]; then
        REVIEW_BASE="$base"
    fi
fi

if [ -n "$REVIEW_BASE" ]; then
    dump_diff_range "$REVIEW_BASE" full
    changed_files=$(get_changed_files_range "$REVIEW_BASE")
elif [ "$MODE" = "consume-findings" ]; then
    # Close path could NOT resolve a non-empty TARGET...HEAD range (get-target
    # errored/empty, or the committed range is empty). The close diff is already
    # committed, so a working-tree dump_diff would emit "No Changes" and the
    # reviewer would validate /code-review's findings against an EMPTY diff —
    # silently shipping unverified findings. Surface it loudly instead of the
    # silent fallback; the reviewer must review the committed close diff manually.
    echo "## Close diff unavailable"
    echo "MODE=consume-findings but the cumulative close range (TARGET...HEAD)"
    echo "could not be resolved (merge target empty/unresolvable, or no"
    echo "divergence). Do NOT treat this as 'no changes': review the committed"
    echo "close diff manually (e.g. \`git diff <merge-target>...HEAD\`) before"
    echo "validating the /code-review findings."
    changed_files=""
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

# Risk signal: project-agnostic content-heuristic classifier scores each
# changed .py file (state-field density, exit/decision blocks, lock/async
# primitives, lifecycle pairs, async complexity). The SKILL routes RISK=high
# to a bounded parallel multi-angle escalation (3 angle-focused reviewer
# spawns); RISK=low keeps the default single-spawn path. Safe-fallback on
# classifier error → RISK=low so a crash never blocks the increment.
echo ""
echo "## Risk Signal"
if [ -z "$changed_files" ]; then
    echo "RISK=low"
    echo "SIGNALS="
else
    # shellcheck disable=SC2086
    python3 "${PLUGIN_ROOT}/skills/xp-quality-review/scripts/risk_classifier.py" \
        $changed_files 2>/dev/null || { echo "RISK=low"; echo "SIGNALS=(classifier error)"; }
fi
