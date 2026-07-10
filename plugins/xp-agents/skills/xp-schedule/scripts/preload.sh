#!/bin/bash
set -euo pipefail
# Preload for xp-schedule: emit the ready frontier (dep-satisfied scheduled
# stories) + its parallelizable verdict so the skill decides solo/parallel
# without a mid-flow CLI call. State-derived — no marker to clear.
# shellcheck source=../../_preload_base.sh
source "$(dirname "$0")/../../_preload_base.sh"

echo "SMM_DIR=${SMM_DIR}"
echo "PLUGIN_ROOT=${PLUGIN_ROOT}"
if [ -f "${SMM_DIR}/sprint.json" ]; then
    echo "SPRINT_FILE=$(sprint_render_to_tempfile)"
fi

# ready-frontier prints {"frontier": [...], "parallelizable": bool, "overlap":
# {"collisions": {...}, "glob_forced": bool}}. Parse it into preload vars;
# fail-safe to an empty frontier if the CLI errors.
REPORT=$(python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "${SMM_DIR}" \
    ready-frontier 2>/dev/null || echo '{"frontier":[],"parallelizable":false,"overlap":{"collisions":{},"glob_forced":false}}')
# Forge-proof scalars (counts + bools) emit directly. Author-influenced
# free text (story ids, collision paths) is captured raw then routed through
# emit_var — the shared sanitizer replaces the inline python flat() so adding a
# preload never re-derives the collapse-whitespace rule. `$(...)` preserves the
# python-emitted newlines; flat() collapses them (join-then-flat == the old
# per-id flat-then-join, so test_schedule_preload.py stays green).
# shellcheck disable=SC2016
python3 -c '
import json, sys
r = json.loads(sys.argv[1])
overlap = r.get("overlap") or {}
print("FRONTIER_COUNT=" + str(len(r.get("frontier", []))))
print("PARALLELIZABLE=" + ("true" if r.get("parallelizable") else "false"))
print("GLOB_FORCED=" + ("true" if overlap.get("glob_forced") else "false"))
' "$REPORT"
# shellcheck disable=SC2016
FRONTIER_IDS_RAW=$(python3 -c '
import json, sys
print(" ".join(str(f) for f in json.loads(sys.argv[1]).get("frontier", [])))
' "$REPORT")
# shellcheck disable=SC2016
OVERLAP_DETAIL_RAW=$(python3 -c '
import json, sys
c = ((json.loads(sys.argv[1]).get("overlap") or {}).get("collisions")) or {}
print("; ".join(f"{p} claimed by " + ", ".join(o["story_id"] for o in owners)
               for p, owners in c.items()))
' "$REPORT")
emit_var FRONTIER_IDS "$FRONTIER_IDS_RAW"
emit_var OVERLAP_DETAIL "$OVERLAP_DETAIL_RAW"

# Emit teammate-support flag. Read the session TEAMMATE_CONFIG marker;
# map token "off" -> false, any other token -> true. Fail-safe to true
# when marker is absent (backward compat: teammates are enabled by default).
TOKEN=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" \
    --smm-dir "${SMM_DIR}" read 2>/dev/null || echo "inherit")
echo "TEAMMATE_ENABLED=$([ "$TOKEN" = "off" ] && echo "false" || echo "true")"
