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
# {"collisions": {...}, "glob_forced": bool, "unscoped": [...]}}. Parse it into
# preload vars; fail-safe to an empty frontier if the CLI errors.
REPORT=$(python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "${SMM_DIR}" \
    ready-frontier 2>/dev/null || echo '{"frontier":[],"parallelizable":false,"overlap":{"collisions":{},"glob_forced":false,"unscoped":[]}}')
# One JSON parse emits all six fields NUL-delimited: three forge-proof scalars
# (counts + bools) plus three author-influenced free-text records (story ids,
# collision paths, unscoped story ids). NUL framing lets a value hold an
# embedded newline without splitting the capture; the free-text records are
# then routed through emit_var — the shared sanitizer stays the single home of
# the collapse-whitespace rule, so adding a preload never re-derives it
# (join-then-flat == the old per-id flat-then-join, so test_schedule_preload.py
# stays green). read -d '' EOF ends the loop cleanly under set -e (a loop
# condition failing is not an error).
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
unscoped = overlap.get("unscoped") or []
# A claim carries "pattern" when a GLOB entry produced it, and then the owner
# never NAMED this path — "claimed by story-001" alone sends the lead to a
# file_domain that does not contain it. Same reason file_domain_lock.
# format_collision_report prints the pattern beside the path.
# No single quotes anywhere in this script: it is bash-single-quoted above.
def _owner(o):
    pat = o.get("pattern")
    return o["story_id"] + (" (via " + pat + ")" if pat else "")

detail = "; ".join(
    f"{p} claimed by " + ", ".join(_owner(o) for o in owners)
    for p, owners in collisions.items()
)
for value in (
    str(len(frontier)),
    "true" if r.get("parallelizable") else "false",
    "true" if overlap.get("glob_forced") else "false",
    " ".join(str(f) for f in frontier),
    detail,
    " ".join(str(s) for s in unscoped),
):
    sys.stdout.write(value + "\0")
' "$REPORT")
echo "FRONTIER_COUNT=${fields[0]:-0}"
echo "PARALLELIZABLE=${fields[1]:-false}"
echo "GLOB_FORCED=${fields[2]:-false}"
emit_var FRONTIER_IDS "${fields[3]:-}"
emit_var OVERLAP_DETAIL "${fields[4]:-}"
emit_var UNSCOPED_IDS "${fields[5]:-}"

# Emit teammate-support flag. Read the session TEAMMATE_CONFIG marker;
# map token "off" -> false, any other token -> true. Fail-safe to true
# when marker is absent (backward compat: teammates are enabled by default).
TOKEN=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" \
    --smm-dir "${SMM_DIR}" read 2>/dev/null || echo "inherit")
echo "TEAMMATE_ENABLED=$([ "$TOKEN" = "off" ] && echo "false" || echo "true")"
