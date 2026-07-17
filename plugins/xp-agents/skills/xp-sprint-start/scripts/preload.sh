#!/bin/bash
set -euo pipefail
# Preload for xp-sprint-start: show milestones and sprint state.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo ""

if ! plan_exists; then
    echo "## ERROR: No execution plan — run /xp-plan."
    exit 0
fi

if ! plan_has_remaining; then
    echo "## ERROR: All milestones delivered — add more via /xp-plan."
    exit 0
fi

echo "## Execution Plan ($(plan_count))"
echo "EXECUTION_PLAN=${SMM_DIR}/execution_plan.json"

check_system_context

# TEST_COMMAND is customer-set free text (system_context.stack.test_command,
# not a git-constrained ref) — route it through emit_var so a newline in it
# cannot forge a downstream preload line. Empty value means the project has
# not declared one; the skill must degrade honestly rather than invent a
# runner (see xp-story-close's preload.sh for the identical pattern).
emit_var TEST_COMMAND "$(find_test_command)"

deferred_count=$(sprint_count_status deferred)
if [ "$deferred_count" -gt 0 ]; then
    echo ""
    echo "## Deferred Stories from Previous Sprint (${deferred_count})"
    echo ""
    sprint_list_stories --status deferred
fi

echo ""
echo "NEXT_SPRINT_ID=$(sprint_next_id)"
