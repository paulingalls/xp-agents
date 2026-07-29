#!/bin/bash
set -euo pipefail
# Preload for xp-assign: emit plan/sprint/SMM paths, clear assign gate.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"
echo "SMM_FILE=$(smm_render_to_tempfile)"

# The teammate prompt must state the session's review cadence, or the lead
# guesses and the teammate runs a per-commit review cycle a story-cadence
# session already defers. Same reader as the story-close and quality-review
# preloads; fail-safes to 'commit'.
echo "REVIEW_CADENCE=$(_get_review_cadence)"

if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# One batch computation emits all four Layer-3 decision vars in a single Python
# startup so the TARGET-IDENTITY INVARIANT cannot drift across duplicated filters:
#   TEAMMATE_STORY_IDS     — the teammate batch /xp-schedule promoted
#                            (in-progress + execution_mode=teammate), consumed by
#                            the skill to split + spawn (symmetric with FRONTIER_IDS).
#   SOLO_TARGET            — a lone in-progress solo story, if any; the skill
#                            selects it BEFORE the batch (solo-first drain).
#   RECOMMENDED_TIER_STORY — the spawn target, resolved SOLO-FIRST and otherwise
#                            as the first un-spawned story in batch order — the
#                            SAME precedence and order the skill pre-flight
#                            applies, so preload and skill never disagree.
#   RECOMMENDED_TIER       — that target's plan-reviewer recommendation (latest
#                            in-sprint tier-recommendation-<target> event wins;
#                            `none` when the plan-reviewer omitted it OR retracted
#                            it (null model) as ambiguous).
#   TEAMMATE_DEFAULT       — the session default tier; fail-safes to `inherit`
#                            (today's behavior) when the TEAMMATE_CONFIG marker is unset.
# Atomic emit: any failure yields the fail-safe defaults (empty batch + none + inherit).
# shellcheck disable=SC2016  # single-quoted python literal; shell must NOT expand it
TEAMMATE_OUT=$(python3 -c '
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path

from markers import read_teammate_config
from sprint_store import load_sprint
from teammate_config_cli import _token_from_config
from worktree import find_teammate_worktree_for_story

smm_dir = Path(sys.argv[3])
cwd = sys.argv[4]
sprint = load_sprint(smm_dir)
teammate_default = _token_from_config(read_teammate_config(smm_dir))
stories = [] if sprint is None else sprint["stories"]
batch = [
    s["id"]
    for s in stories
    if s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
]

# Solo target: a single in-progress solo story is the in-place execution-shape
# target (story-008), INDEPENDENT of the teammate batch — a mixed frontier must
# stay routable, or a pulled-forward solo story is unassignable for as long as
# any teammate is in flight. A solo frontier promotes exactly one story; >1
# in-progress solo is ambiguous -> empty, which the skill cannot tell from "no
# solo story" — so pre-flight re-checks SPRINT_FILE for a live solo story before
# it selects the batch (empty SOLO_TARGET is not proof the drain is over).
solo_in_progress = [
    s["id"]
    for s in stories
    if s.get("status") == "in-progress" and s.get("execution_mode") == "solo"
]
solo_target = solo_in_progress[0] if len(solo_in_progress) == 1 else ""

# Spawn target, SOLO-FIRST — the same precedence the skill pre-flight applies,
# so the advertised target and the resolved one agree (on a mismatch the skill
# discards RECOMMENDED_TIER and the story spawns at the default tier). Absent a
# solo target it is the first un-spawned story in batch order, and the skill
# iterates TEAMMATE_STORY_IDS in that same order.
if solo_target:
    target = solo_target
else:
    target = ""
    for sid in batch:
        if not find_teammate_worktree_for_story(sid, cwd):
            target = sid
            break

tier = "none"
effort = ""
if target:
    topic = "tier-recommendation-" + target
    # Scope to the current sprint window: per-sprint story ids (story-001...)
    # are reused every sprint, so a prior sprint can leave a stale
    # recommendation under an identical topic. Date-granular compare on the
    # sprint started field mirrors retro_metrics._event_in_sprint_window;
    # empty started (no scoping anchor) accepts all events.
    sprint_start = ((sprint or {}).get("started") or "")
    events_file = smm_dir / "events.jsonl"
    if events_file.exists():
        # Reverse-scan with early-exit: the latest matching in-window event
        # wins, so the first hit walking from the tail IS the answer. Avoids
        # json.loads-ing the entire log every preload (the common case has the
        # recommendation near the tail). Equivalent to the forward "last write
        # wins" scan, just without parsing every earlier line.
        for line in reversed(events_file.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("topic") != topic:
                continue
            if event.get("type") != "decision":
                continue  # the plan-reviewer writes the recommendation as a decision
            if sprint_start and event.get("ts", "")[:10] < sprint_start:
                continue  # stale recommendation from an earlier sprint
            # First topic+type+window match walking from the tail IS the latest
            # event — break unconditionally. A retraction (recommended_model
            # null, emitted when a re-review finds the story ambiguous) thus
            # beats an earlier real recommendation: null model -> "none".
            # recommended_effort (story-004) travels on the SAME winning event,
            # so a retraction (no effort key) naturally yields empty —
            # RECOMMENDED_EFFORT never survives from a stale earlier
            # recommendation. (The persisted executor_effort FIELD no longer
            # latches either: Step 0 passes `set-executor --effort` every spawning
            # branch, value-or-null, so a retraction clears it. executor_model is
            # left to the Step 0 --model flag, OMITTED on the inherit outcome to
            # preserve a deliberate /xp-schedule pre-seed.)
            metadata = event.get("metadata") or {}
            tier = metadata.get("recommended_model") or "none"
            effort = metadata.get("recommended_effort") or ""
            break

print("\n".join([
    "TEAMMATE_STORY_IDS=" + " ".join(batch),
    "SOLO_TARGET=" + solo_target,
    "RECOMMENDED_TIER_STORY=" + target,
    "RECOMMENDED_TIER=" + tier,
    "RECOMMENDED_EFFORT=" + effort,
    "TEAMMATE_DEFAULT=" + teammate_default,
]))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "$(pwd)" 2>/dev/null) \
    || TEAMMATE_OUT=""
if [ -z "$TEAMMATE_OUT" ]; then
    TEAMMATE_OUT=$'TEAMMATE_STORY_IDS=\nSOLO_TARGET=\nRECOMMENDED_TIER_STORY=\nRECOMMENDED_TIER=none\nRECOMMENDED_EFFORT=\nTEAMMATE_DEFAULT=inherit'
fi
echo "$TEAMMATE_OUT"

# Plan path persisted by xp-review-plan preload — guarded against a stale
# plan authored for a DIFFERENT story than the resolved spawn target
# (debt 2491b4d3e025). ".last-plan-path" holds only a path (no story id)
# and is overwritten by every /xp-review-plan, so if the lead planned
# several stories before assigning it can name the LATEST plan while the
# target is the lowest un-spawned story. Emission runs AFTER the Python
# block above so PLAN_TARGET is known.
#
# The owning story is read from the H1 ALONE — the first `# ` heading — not
# from any matching line in the body. A plan quoting a commit message or a
# fenced snippet beginning `# story-NNN` is not a plan FOR that story, and
# treating it as one hard-stops /xp-assign on a plan that is in fact correct.
#
# Fails CLOSED: an empty PLAN_TARGET means the target could not be resolved
# (empty batch, or the Python block above failed — its stderr is discarded, so
# the two are indistinguishable here), and emitting then hands over exactly the
# stale plan this guard exists to suppress, on the path where resolution is
# already unhealthy. A plan whose H1 claims no story stays emittable: it was
# never attributable, so withholding it would be a false negative.
PLAN_TARGET=$(printf '%s\n' "$TEAMMATE_OUT" | sed -n 's/^RECOMMENDED_TIER_STORY=//p')
PLAN_MARKER="${SMM_DIR}/.last-plan-path"
if [ -f "$PLAN_MARKER" ]; then
    PLAN_PATH=$(cat "$PLAN_MARKER")
    if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
        # Story id declared by the H1, or empty when the H1 declares none.
        # awk exits at the FIRST heading, so only that line can match.
        PLAN_H1_STORY=$(awk '/^#[[:space:]]/ {
            if (match($0, /^#[[:space:]]+story-[0-9]+/)) {
                s = substr($0, RSTART, RLENGTH)
                sub(/^#[[:space:]]+/, "", s)
                print s
            }
            exit
        }' "$PLAN_PATH")
        if [ -z "$PLAN_H1_STORY" ] || [ "$PLAN_H1_STORY" = "$PLAN_TARGET" ]; then
            emit_path_var PLAN_FILE "$PLAN_PATH"
        fi
    fi
fi

rm -f "${SMM_DIR}/.assign-pending"
