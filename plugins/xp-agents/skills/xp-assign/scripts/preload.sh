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

# The teammate batch /xp-schedule already promoted: in-progress stories whose
# execution_mode is teammate. Computed in Python (no selection math in the
# skill) — the narrowed xp-assign consumes TEAMMATE_STORY_IDS to split + spawn,
# symmetric with /xp-schedule's FRONTIER_IDS. Always emitted (empty when none).
echo "TEAMMATE_STORY_IDS=$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from pathlib import Path
from sprint_store import load_sprint
sprint = load_sprint(Path(sys.argv[3]))
ids = [] if sprint is None else [
    s["id"] for s in sprint["stories"]
    if s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
]
print(" ".join(ids))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" 2>/dev/null || echo "")"

# Layer-3 decision inputs (story-003): the session default tier and the
# plan-reviewer's per-story recommendation. Both feed the SKILL.md behavior
# table. TEAMMATE_DEFAULT fail-safes to `inherit` (today's behavior) when the
# TEAMMATE_CONFIG marker is unset.
echo "TEAMMATE_DEFAULT=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" --smm-dir "${SMM_DIR}" read 2>/dev/null || echo inherit)"

# RECOMMENDED_TIER is computed for the SAME story the skill's pre-flight
# spawns — the first un-spawned teammate story in TEAMMATE_STORY_IDS order
# (sprint array order, normally id-ascending) — so preload and skill never
# disagree on the target (TARGET-IDENTITY INVARIANT). RECOMMENDED_TIER_STORY
# pins that identity. Fail-safe to `none` when no recommendation event exists
# (the plan-reviewer omit-when-ambiguous case).
TIER_OUT=$(python3 -c '
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path

from sprint_store import load_sprint
from worktree import find_teammate_worktree_for_story

smm_dir = Path(sys.argv[3])
cwd = sys.argv[4]
sprint = load_sprint(smm_dir)
target = ""
if sprint is not None:
    # Iterate stories in the SAME order the TEAMMATE_STORY_IDS block emits
    # (sprint["stories"] array order) — the skill pre-flight consumes that
    # list verbatim, so re-sorting here could pick a different target and
    # break the TARGET-IDENTITY INVARIANT when the array is not id-ordered.
    batch = [
        s["id"]
        for s in sprint["stories"]
        if s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
    ]
    for sid in batch:
        if not find_teammate_worktree_for_story(sid, cwd):
            target = sid
            break

tier = "none"
if target:
    events_file = smm_dir / "events.jsonl"
    topic = "tier-recommendation-" + target
    if events_file.exists():
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("topic") == topic:
                model = (event.get("metadata") or {}).get("recommended_model")
                if model:
                    tier = model  # latest matching event wins

print("RECOMMENDED_TIER_STORY=" + target)
print("RECOMMENDED_TIER=" + tier)
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "$(pwd)" 2>/dev/null) \
    || TIER_OUT=""
if [ -z "$TIER_OUT" ]; then
    TIER_OUT=$'RECOMMENDED_TIER_STORY=\nRECOMMENDED_TIER=none'
fi
echo "$TIER_OUT"

rm -f "${SMM_DIR}/.assign-pending"
