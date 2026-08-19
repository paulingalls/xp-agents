#!/bin/bash
set -euo pipefail
# Preload for xp-plan-reviewer: emits file paths for agent to Read.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"

# Plan path from marker set by post_tool_exit_plan.py. When the marker is
# absent (consumed by a review that COMPLETED — subagent_stop discharges it, not
# this script) but .last-plan-path names a file that still exists, this is a
# re-review, a second pass someone asked for explicitly, not a misfire. Nothing
# DEMANDS that pass: the reviewer's blocking Next-step option routes forward,
# not back into another round.
#
# This script spends NO gate. The discharge used to live at its end, which put
# it at review START: an opened-and-abandoned review left the lead un-gated, and
# on the harness where a shell read of SKILL.md triggers the preload, reading the
# skill body was enough. The `rm -f` below is a different act — see it there.
#
# ACCEPTED LIMIT: .last-plan-path is NOT session-scoped. A later session with
# no marker falls back to the PREVIOUS session's plan while that file exists,
# so PLAN_SOURCE=last-reviewed carries no freshness guarantee. Accepted because
# xp-assign's preload already reads this same file cross-session — the fallback
# inherits that staleness shape rather than adding a new one.
MARKER="${SMM_DIR}/.plan-awaiting-review"
LAST_PLAN_PATH_FILE="${SMM_DIR}/.last-plan-path"
PLAN_PATH=""
PLAN_SOURCE=""
if [ -f "$MARKER" ]; then
    PLAN_PATH=$(cat "$MARKER")
    PLAN_SOURCE="marker"
elif [ -f "$LAST_PLAN_PATH_FILE" ]; then
    PLAN_PATH=$(cat "$LAST_PLAN_PATH_FILE")
    PLAN_SOURCE="last-reviewed"
fi

# Misfire short-circuit — skip SMM/sprint renders when there's no valid plan.
if [ -z "$PLAN_PATH" ] || [ ! -f "$PLAN_PATH" ]; then
    if [ -f "$MARKER" ]; then
        case "$PLAN_PATH" in
        */*)
            # A PATH that names nothing. Unsatisfiable: no review can ever clear
            # the gate this arms, so a lead holding it would be write-blocked
            # with no act available. Collect it — the plan has to be re-entered,
            # which re-arms from scratch.
            #
            # Through the marker helper, load-bearing twice over: it is the
            # convention (one spelling of the filename, symlink refusal), and it
            # keeps this act spelled DIFFERENTLY from the discharge that used to
            # sit at the end of this script. The mutation registry keys a site on
            # (script, verb, target), so while both were `rm -f "$MARKER"` the two
            # collapsed into one entry and a re-added discharge would have been
            # absorbed by this one, unnoticed.
            echo "PLAN_FILE_ERROR=Marker '$(flat "$PLAN_PATH")' invalid — it names a plan file that does not exist. Re-enter plan mode or check ~/.claude/plans/."
            # Clear the stale last-reviewed pointer too — otherwise the NEXT
            # invocation silently resurrects the previously reviewed plan
            # instead of reporting the loud "no plan" error it should.
            rm -f "$LAST_PLAN_PATH_FILE"
            consume_marker PLAN_AWAITING_REVIEW
            ;;
        *)
            # NOT a path — the shape the plugin arms routinely. `subagent_stop`'s
            # Plan-via-Agent-tool leg has no plan path in its payload and writes
            # the agent id; `post_tool_exit_plan` falls back to the same when
            # ExitPlanMode hands over no filePath.
            #
            # Do NOT collect it. The case above is "the plan is gone"; this one is
            # "the plan exists, only its location is unknown", and consuming here
            # is what let a plain `cat` of this SKILL.md spend the gate with no
            # review — the defect this story exists to remove. The lead is not
            # stranded: re-entering plan mode re-arms through ExitPlanMode with a
            # real path, and plan files are exempt from the gate meanwhile.
            echo "PLAN_FILE_ERROR=The plan marker records no plan path (it holds '$(flat "$PLAN_PATH")'). Re-enter plan mode so the marker is re-armed with the plan's location, then re-run."
            ;;
        esac
    else
        echo "PLAN_FILE_ERROR=No plan marker. Run EnterPlanMode/ExitPlanMode first."
    fi
    exit 0
fi

if [ -f "${SMM_DIR}/shared_mental_model.json" ]; then
    echo "SMM_FILE=$(smm_render_to_tempfile)"
fi

if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

emit_system_context_rendered_for plan-reviewer

emit_path_var PLAN_FILE "$PLAN_PATH"
emit_var PLAN_SOURCE "$PLAN_SOURCE"
echo "$PLAN_PATH" > "${SMM_DIR}/.last-plan-path"
