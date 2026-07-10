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
# One JSON parse emits all five fields NUL-delimited: three forge-proof scalars
# (counts + bools) plus two author-influenced free-text records (story ids,
# collision paths). NUL framing lets a value hold an embedded newline without
# splitting the capture; the free-text records are then routed through emit_var —
# the shared sanitizer stays the single home of the collapse-whitespace rule, so
# adding a preload never re-derives it (join-then-flat == the old per-id
# flat-then-join, so test_schedule_preload.py stays green). read -d '' EOF ends
# the loop cleanly under set -e (a loop condition failing is not an error).
# shellcheck disable=SC2016
fields=()
while IFS= read -r -d '' field; do
    fields+=("$field")
done < <(python3 -c '
import json, sys
r = json.loads(sys.argv[1])
overlap = r.get("overlap") or {}
frontier = r.get("frontier", [])
collisions = overlap.get("collisions") or {}
detail = "; ".join(
    f"{p} claimed by " + ", ".join(o["story_id"] for o in owners)
    for p, owners in collisions.items()
)
for value in (
    str(len(frontier)),
    "true" if r.get("parallelizable") else "false",
    "true" if overlap.get("glob_forced") else "false",
    " ".join(str(f) for f in frontier),
    detail,
):
    sys.stdout.write(value + "\0")
' "$REPORT")
echo "FRONTIER_COUNT=${fields[0]:-0}"
echo "PARALLELIZABLE=${fields[1]:-false}"
echo "GLOB_FORCED=${fields[2]:-false}"
emit_var FRONTIER_IDS "${fields[3]:-}"
emit_var OVERLAP_DETAIL "${fields[4]:-}"

# Emit teammate-support flag. Read the session TEAMMATE_CONFIG marker;
# map token "off" -> false, any other token -> true. Fail-safe to true
# when marker is absent (backward compat: teammates are enabled by default).
TOKEN=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" \
    --smm-dir "${SMM_DIR}" read 2>/dev/null || echo "inherit")
echo "TEAMMATE_ENABLED=$([ "$TOKEN" = "off" ] && echo "false" || echo "true")"
