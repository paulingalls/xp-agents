#!/bin/bash
set -euo pipefail
# Preload for xp-accept: reviewing-first dispatch with in-progress fallback.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

SPRINT_FILE="${SMM_DIR}/sprint.json"

echo "SMM_DIR=${SMM_DIR}"
echo ""

if ! sprint_exists; then
    echo "### ERROR"
    echo "No sprint.json found. Nothing to accept."
    exit 0
fi

# Reviewing-first: teammate self-promote lands stories in `reviewing`;
# solo work leaves them in `in-progress`. Process finished teammate work
# before any in-progress fallback when both coexist.
reviewing_count=$(sprint_count_status reviewing)
in_progress_count=$(sprint_count_status in-progress)

if [ "$reviewing_count" -gt 0 ]; then
    SELECTED_STATUS=reviewing
    SELECTED_COUNT=$reviewing_count
elif [ "$in_progress_count" -gt 0 ]; then
    SELECTED_STATUS=in-progress
    SELECTED_COUNT=$in_progress_count
else
    echo "### NO_STORIES_TO_ACCEPT"
    echo "No reviewing or in-progress stories to accept."
    exit 0
fi

# Clear the ACCEPT marker here so update-story done is unblocked; the agent
# is never asked to run rm.
consume_marker ACCEPT

# Arm ACCEPT_IN_FLIGHT for the whole accept session: Step 1.0 promotes the
# story to `reviewing` before tests run, so the stop gate would otherwise
# tell the agent to "run /xp-accept" while it is already inside this skill
# (notably while awaiting background acceptance tests). sprint_stop_gate
# defers on this marker; review_cycle_done consumes it on accept's terminal
# dispatch (/xp-schedule or /xp-sprint-review completion — no SKILL prose step),
# and the SessionStart sweep clears it if accept is abandoned before that.
write_marker ACCEPT_IN_FLIGHT "1"

echo "### STORIES_TO_ACCEPT"
echo "Sprint has ${SELECTED_COUNT} ${SELECTED_STATUS} stories to verify."
echo "SELECTED_STATUS=${SELECTED_STATUS}"
echo "SPRINT_FILE=${SPRINT_FILE}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python3 "${SKILL_DIR}/scripts/concern_triage.py" --smm-dir "${SMM_DIR}" --sprint-file "${SPRINT_FILE}" || true
echo ""

python3 "${SKILL_DIR}/scripts/acceptance_types.py" --sprint-file "${SPRINT_FILE}" || true
echo ""

# Read-only prepare-readiness snapshot for the serial main-checkout
# acceptance flow. One tab-delimited row per live teammate worktree —
# `story-id<TAB>abs-path<TAB>tip-sha<TAB>restore-ref` (macOS paths can
# contain spaces) — plus a trailing `MAIN_STATE<TAB><state>` line when the
# main checkout needs recovery (in-progress-merge | detached-HEAD | dirty)
# before a detached-HEAD acceptance run. Side-effect-free; the SKILL drives
# accept-env prepare/restore per row off this data.
accept_env=$(python3 "${PLUGIN_ROOT}/scripts/branching.py" --smm-dir "${SMM_DIR}" \
    accept-env inspect --cwd . 2>/dev/null || true)
if [ -n "$accept_env" ]; then
    echo ""
    echo "### TEAMMATE_WORKTREES"
    # Sanitize each TAB field (paths can carry whitespace on macOS) while
    # preserving the tab field-sep + newline row-sep framing the SKILL splits on.
    printf '%s\n' "$accept_env" | sanitize_tsv_block
fi
