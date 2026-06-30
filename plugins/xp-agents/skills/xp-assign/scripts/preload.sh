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

# Layer-3 decision input: the session default tier. Fail-safes to `inherit`
# (today's behavior) when the TEAMMATE_CONFIG marker is unset.
echo "TEAMMATE_DEFAULT=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" --smm-dir "${SMM_DIR}" read 2>/dev/null || echo inherit)"

# One batch computation emits all three target-coupled vars so the
# TARGET-IDENTITY INVARIANT cannot drift across duplicated filters:
#   TEAMMATE_STORY_IDS     — the teammate batch /xp-schedule promoted
#                            (in-progress + execution_mode=teammate), consumed by
#                            the skill to split + spawn (symmetric with FRONTIER_IDS).
#   RECOMMENDED_TIER_STORY — the spawn target: the first un-spawned story in batch
#                            order, the SAME order the skill pre-flight consumes
#                            TEAMMATE_STORY_IDS, so preload and skill never disagree.
#   RECOMMENDED_TIER       — that target's plan-reviewer recommendation (latest
#                            tier-recommendation-<target> event wins; `none` when
#                            the plan-reviewer omitted it as ambiguous).
# Atomic emit: any failure yields the fail-safe defaults (empty batch + none).
TEAMMATE_OUT=$(python3 -c '
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
batch = [] if sprint is None else [
    s["id"]
    for s in sprint["stories"]
    if s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
]

# Spawn target: the first un-spawned story in batch order. The skill pre-flight
# iterates TEAMMATE_STORY_IDS in this same order, so the two never disagree.
target = ""
for sid in batch:
    if not find_teammate_worktree_for_story(sid, cwd):
        target = sid
        break

tier = "none"
if target:
    topic = "tier-recommendation-" + target
    events_file = smm_dir / "events.jsonl"
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

print("\n".join([
    "TEAMMATE_STORY_IDS=" + " ".join(batch),
    "RECOMMENDED_TIER_STORY=" + target,
    "RECOMMENDED_TIER=" + tier,
]))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "$(pwd)" 2>/dev/null) \
    || TEAMMATE_OUT=""
if [ -z "$TEAMMATE_OUT" ]; then
    TEAMMATE_OUT=$'TEAMMATE_STORY_IDS=\nRECOMMENDED_TIER_STORY=\nRECOMMENDED_TIER=none'
fi
echo "$TEAMMATE_OUT"

rm -f "${SMM_DIR}/.assign-pending"
