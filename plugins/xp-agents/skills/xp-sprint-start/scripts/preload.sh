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

# One read, not a count-then-list pair: sprint-close archives sprint.json away,
# so this has to consult the newest archive, and two reads of a moving target
# can disagree about whether there is anything to show.
carryover=$(sprint_list_carryover)
if [ -n "$carryover" ]; then
    # Count STORY: lines only. `wc -l` over the whole block would count the
    # SOURCE:/WARNING: lines as stories, and counting `^story-` keyed on the
    # DATA: an id is only schema-checked as a string, so it both missed an id
    # shaped differently and counted a line a forged id had smuggled in. The
    # prefix is emitted by us, and the command collapses each record to one line.
    carryover_count=$(printf '%s\n' "$carryover" | grep -c '^STORY: ' || true)
    echo ""
    echo "## Deferred Stories from Previous Sprint (${carryover_count})"
    echo ""
    printf '%s\n' "$carryover"
fi

echo ""
echo "NEXT_SPRINT_ID=$(sprint_next_id)"
