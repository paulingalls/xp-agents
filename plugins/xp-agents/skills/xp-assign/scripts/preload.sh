#!/bin/bash
set -euo pipefail
# Preload for xp-assign: emit plan/sprint/SMM paths, clear assign gate.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"
echo "SMM_FILE=$(smm_render_to_tempfile)"

# Plan path persisted by xp-review-plan preload
PLAN_MARKER="${SMM_DIR}/.last-plan-path"
if [ -f "$PLAN_MARKER" ]; then
    PLAN_PATH=$(cat "$PLAN_MARKER")
    if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
        echo "PLAN_FILE=${PLAN_PATH}"
    fi
fi

if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# One batch computation emits all four Layer-3 decision vars in a single Python
# startup so the TARGET-IDENTITY INVARIANT cannot drift across duplicated filters:
#   TEAMMATE_STORY_IDS     — the teammate batch /xp-schedule promoted
#                            (in-progress + execution_mode=teammate), consumed by
#                            the skill to split + spawn (symmetric with FRONTIER_IDS).
#   RECOMMENDED_TIER_STORY — the spawn target: the first un-spawned story in batch
#                            order, the SAME order the skill pre-flight consumes
#                            TEAMMATE_STORY_IDS, so preload and skill never disagree.
#   RECOMMENDED_TIER       — that target's plan-reviewer recommendation (latest
#                            in-sprint tier-recommendation-<target> event wins;
#                            `none` when the plan-reviewer omitted it as ambiguous).
#   TEAMMATE_DEFAULT       — the session default tier; fail-safes to `inherit`
#                            (today's behavior) when the TEAMMATE_CONFIG marker is unset.
# Atomic emit: any failure yields the fail-safe defaults (empty batch + none + inherit).
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

# Solo target: with no teammate batch, a single in-progress solo story is the
# in-place execution-shape target (story-008). A solo frontier promotes exactly
# one story; >1 in-progress solo is ambiguous -> empty (the skill stops).
solo_in_progress = [
    s["id"]
    for s in stories
    if s.get("status") == "in-progress" and s.get("execution_mode") == "solo"
]
solo_target = solo_in_progress[0] if (not batch and len(solo_in_progress) == 1) else ""

# Spawn target: the first un-spawned story in batch order. The skill pre-flight
# iterates TEAMMATE_STORY_IDS in this same order, so the two never disagree.
# Falls back to the solo target so the tier lookup + pin cover the solo story.
target = ""
for sid in batch:
    if not find_teammate_worktree_for_story(sid, cwd):
        target = sid
        break
if not target:
    target = solo_target

tier = "none"
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
            model = (event.get("metadata") or {}).get("recommended_model")
            if model:
                tier = model  # most-recent matching in-window event wins
                break

print("\n".join([
    "TEAMMATE_STORY_IDS=" + " ".join(batch),
    "SOLO_TARGET=" + solo_target,
    "RECOMMENDED_TIER_STORY=" + target,
    "RECOMMENDED_TIER=" + tier,
    "TEAMMATE_DEFAULT=" + teammate_default,
]))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "$(pwd)" 2>/dev/null) \
    || TEAMMATE_OUT=""
if [ -z "$TEAMMATE_OUT" ]; then
    TEAMMATE_OUT=$'TEAMMATE_STORY_IDS=\nSOLO_TARGET=\nRECOMMENDED_TIER_STORY=\nRECOMMENDED_TIER=none\nTEAMMATE_DEFAULT=inherit'
fi
echo "$TEAMMATE_OUT"

rm -f "${SMM_DIR}/.assign-pending"
