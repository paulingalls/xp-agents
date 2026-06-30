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

# ready-frontier prints {"frontier": [...], "parallelizable": bool}. Parse it
# into preload vars; fail-safe to an empty frontier if the CLI errors.
REPORT=$(python3 "${PLUGIN_ROOT}/smm/sprint_cli.py" --smm-dir "${SMM_DIR}" \
    ready-frontier 2>/dev/null || echo '{"frontier":[],"parallelizable":false}')
python3 -c '
import json, sys
r = json.loads(sys.argv[1])
frontier = r.get("frontier", [])
print("FRONTIER_IDS=" + " ".join(frontier))
print("FRONTIER_COUNT=" + str(len(frontier)))
print("PARALLELIZABLE=" + ("true" if r.get("parallelizable") else "false"))
' "$REPORT"

# Emit teammate-support flag. Read the session TEAMMATE_CONFIG marker;
# map token "off" -> false, any other token -> true. Fail-safe to true
# when marker is absent (backward compat: teammates are enabled by default).
TOKEN=$(python3 "${PLUGIN_ROOT}/scripts/teammate_config_cli.py" \
    --smm-dir "${SMM_DIR}" read 2>/dev/null || echo "inherit")
echo "TEAMMATE_ENABLED=$([ "$TOKEN" = "off" ] && echo "false" || echo "true")"
