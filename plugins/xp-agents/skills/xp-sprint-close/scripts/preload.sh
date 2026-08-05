#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-close: surface the five fields the close skill
# orchestrates against (current/target branch, gh availability, dirty
# state).
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-target --cwd . 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
# Route branch refs through emit_var for a uniform emit path across the close
# family (git refs can't forge a line, but keeping every emit consistent avoids
# reading as a gap). Shell vars stay raw for downstream use.
emit_var CURRENT_BRANCH "${CURRENT_BRANCH}"
emit_var TARGET_BRANCH "${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
# Threshold-gated full code review (shared Step 4b): emit CLOSE_CODE_FILE_COUNT
# + RUN_FULL_CODE_REVIEW for the cumulative close diff. Story-close omits this.
python3 "${PLUGIN_ROOT}/scripts/close_common.py" close-review-gate \
    --cwd . --target "${TARGET_BRANCH}" 2>/dev/null \
    || echo "RUN_FULL_CODE_REVIEW=false"

# Verify-acceptance gate signal (M6): the last sprint-verify rerun's status.
# Exit 1 (red) is a gate signal, not an error — keep the preload green and
# default an empty/error read to "none" (no gate when no sprint/event exists).
VERIFY_STATUS=$(python3 "${PLUGIN_ROOT}/scripts/verify_acceptance.py" \
    --query-verify-status --smm-dir "${SMM_DIR}" 2>/dev/null | head -1) || true
echo "VERIFY_STATUS=${VERIFY_STATUS:-none}"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
# Record an AGED survivor before arming over it: the arm below overwrites the
# marker, so a previous cycle's evidence has to be read out first. Whether the
# survivor is abandoned at all is the recorder's call, not this line's — see
# scripts/close_cycle_abandonment.py; a young one (this close's own red-gate
# retry) and no survivor at all both record nothing.
#
# BEFORE CLOSE_START_TS, deliberately: Step 6's abort-default and the
# auto-merge gate both count high concerns raised AFTER that stamp, and this
# record is about the PREVIOUS cycle.
python3 "${PLUGIN_ROOT}/scripts/close_cycle_abandonment.py" \
    --smm-dir "${SMM_DIR}" --detector close_restart 2>/dev/null || true
echo "CLOSE_START_TS=$(now_iso)"
CLOSE_CYCLE_ID=$(generate_id)
echo "CLOSE_CYCLE_ID=${CLOSE_CYCLE_ID}"
emit_close_started_event sprint "${CLOSE_CYCLE_ID}"
# Persist the id where a LATER process can read it. The echo above reaches the
# LLM only, and a concern raised mid-close is appended by a separate process —
# without the marker the merge gate is back to inferring which concerns belong
# to this close from the `files` they happened to record.
#
# write_marker ends in `2>/dev/null || true`, so a failed write is SILENT. That
# degrades safely rather than being guaranteed: no id on disk means no stamp,
# and an unstamped concern is still counted by the gate under the shipped
# files-relevance rule. It is never the reason a close fails to start.
write_marker CLOSE_CYCLE_ID "${CLOSE_CYCLE_ID}"
emit_system_context_rendered_for close-reviewer
# Arm the close-cycle Stop gate deterministically — prose-driven write
# was unreliable when the LLM skipped or reordered the invocation.
#
# Armed through the recorder rather than write_marker so the marker carries
# the session that OWNS this close. That payload is the only thing letting a
# detector in another window tell a running close from an abandoned one; a
# duration cannot, because a close's runtime is unbounded.
python3 "${PLUGIN_ROOT}/scripts/close_cycle_abandonment.py" \
    --smm-dir "${SMM_DIR}" --arm-only 2>/dev/null \
    || write_marker CLOSE_CYCLE_ACTIVE ""
emit_hook_guidance "$HOOK_STATUS"

# Append the close-pipeline reference so the LLM sees one consistent set of
# shared instructions instead of near-duplicate inlined copies.
#
# Two files, in this order. The review reference (Steps 4, 4b) is emitted only
# by the modes that RUN those steps — story-close defers both to its enclosing
# sprint-close, so it appends the shared file alone. Splitting the doc rather
# than filtering headings out of one keeps the mode scoping structural: a
# renamed heading cannot silently drop a section.
#
# Review file FIRST so Step 4 still precedes Step 5.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_review.md"
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
