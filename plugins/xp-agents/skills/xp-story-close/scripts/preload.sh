#!/bin/bash
set -euo pipefail
# Preload for xp-story-close: surface the five fields the close skill
# orchestrates against. TARGET_BRANCH is the story base (sprint branch
# at stage 2+, primary otherwise) — story-close merges a story branch
# into its sprint base, never directly into a plan/primary branch
# during sprint execution.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

# Implicit teammate-worktree discovery: when
# /xp-accept dispatches /xp-story-close after marking a teammate story
# done, the orchestrator sits on the SPRINT branch — not the story
# branch. Pair the live teammate worktree against sprint.json status
# to discover the worktree of the just-done story; emit TEAMMATE_CWD
# + override CURRENT_BRANCH from the worktree's HEAD. Empty TEAMMATE_CWD
# means solo flow (orchestrator IS on the story branch).
#
# Multi-match (two `done` stories with live worktrees) signals broken
# /xp-accept iteration — surface the helper's stderr and propagate the
# non-zero exit (set -e) rather than masking it as solo flow. The
# helper's "fail loud" contract only holds if its callers don't swallow.
#
# CLI emits `<abs-path>\t<branch>`: tab is the unambiguous split
# point — worktree paths can contain spaces on macOS.
CLOSING=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" find-closing-teammate-worktree --cwd .)
if [ -n "$CLOSING" ]; then
    TEAMMATE_CWD="${CLOSING%$'\t'*}"
    CURRENT_BRANCH="${CLOSING##*$'\t'}"
else
    TEAMMATE_CWD=""
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi
TARGET_BRANCH=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" get-base --cwd . 2>/dev/null || echo "")

echo "SMM_DIR=${SMM_DIR}"
echo "TEAMMATE_CWD=${TEAMMATE_CWD}"
echo "CURRENT_BRANCH=${CURRENT_BRANCH}"
echo "TARGET_BRANCH=${TARGET_BRANCH}"
echo "GH_AVAILABLE=$(gh_available)"
echo "WORKTREE_CLEAN=$(worktree_clean)"
HOOK_STATUS=$(pre_commit_hook_present)
echo "PRE_COMMIT_HOOK=${HOOK_STATUS}"
echo "TEST_COMMAND=$(find_test_command)"
echo "CLOSE_START_TS=$(now_iso)"
echo "CLOSE_CYCLE_ID=$(generate_id)"

# Verify-touch gate: declared acceptance-test paths no commit on
# base..HEAD touched, plus whether a [verify-deferred] commit defers
# the gate. The close skill refuses on untouched && not-deferred.
# `|| true` keeps the CLI's exit 1 (untouched paths found) from tripping
# `set -e` — we want its stdout regardless of exit code. VERIFY_UNTOUCHED
# is space-joined (acceptance-test paths carry no spaces).
STORY_ID=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" \
    --smm-dir "${SMM_DIR}" extract-story-id --branch "${CURRENT_BRANCH}")
VERIFY_UNTOUCHED=""
VERIFY_DEFERRED="false"
if [ -n "$STORY_ID" ]; then
    UNTOUCHED=$(python3 "${PLUGIN_ROOT}/scripts/verify_paths.py" \
        --smm-dir "${SMM_DIR}" --cwd "${TEAMMATE_CWD:-.}" \
        --story "$STORY_ID" --base "${TARGET_BRANCH}" 2>/dev/null) || true
    VERIFY_UNTOUCHED=$(printf '%s' "$UNTOUCHED" | tr '\n' ' ' | sed 's/ *$//')
    # Single source for the [verify-deferred] marker: commit_handling reuses
    # parse_verify_deferred (no duplicate bash regex of the marker).
    VERIFY_DEFERRED=$(python3 "${PLUGIN_ROOT}/scripts/commit_handling.py" \
        has-verify-deferred --cwd "${TEAMMATE_CWD:-.}" --base "${TARGET_BRANCH}" \
        2>/dev/null) || VERIFY_DEFERRED="false"
fi
echo "VERIFY_UNTOUCHED=${VERIFY_UNTOUCHED}"
echo "VERIFY_DEFERRED=${VERIFY_DEFERRED}"

# Cadence routes Step 4.5: 'story' runs the full review cycle here (the
# per-commit gate deferred it); 'commit'/unset keeps the close-reviewer
# fork. read_review_cadence fail-safes to 'commit'.
CADENCE=$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
print(markers.read_review_cadence(Path(sys.argv[3])))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" 2>/dev/null || echo commit)
if [ "$CADENCE" = "story" ]; then
    echo "REVIEW_PATH=full-cycle"
else
    echo "REVIEW_PATH=close-reviewer"
fi

emit_system_context_rendered_for close-reviewer
emit_hook_guidance "$HOOK_STATUS"

# Append shared close-pipeline reference (Steps 5, 5b, 6) so the LLM
# sees one consistent set of shared instructions across all four close
# skills instead of four near-duplicate inlined copies.
echo
cat "${PLUGIN_ROOT}/scripts/_close_pipeline_shared.md"
