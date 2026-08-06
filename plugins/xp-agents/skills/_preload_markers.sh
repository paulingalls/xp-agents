#!/bin/bash
# Marker helpers for preloads — thin wrappers over scripts/markers.py.
#
# Extracted from _preload_base.sh when that file crossed its 500-line cap, the
# same move that produced _preload_emit.sh, _preload_diff.sh and
# _preload_liveness.sh. Sourced by _preload_base.sh, so every preload gets these
# transitively with no call-site changes. Not executable on its own: it relies on
# PLUGIN_ROOT and SMM_DIR being set by the base.
#
# Usage: consume_marker ACCEPT
#        write_marker NEEDS_HOUSEKEEPING "kickoff"
#        if marker_exists HOUSEKEEPING_ARMED; then ...
#
# All three take the MarkerDef CONSTANT NAME, never a filename. That is
# load-bearing: MarkerDef.filename() is what resolves an agent- or
# session-scoped suffix, so a hand-rolled "$SMM_DIR/.some-marker" path would
# silently address the wrong file for exactly the markers that need scoping — and
# would skip the symlink refusal too.
#
# Values are passed via sys.argv so content with quotes/backslashes is safe.

consume_marker() {
    local marker_name="$1"
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
markers.marker_consume(Path(sys.argv[3]), getattr(markers, sys.argv[4]))
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "${marker_name}" 2>/dev/null || true
}

write_marker() {
    local marker_name="$1"
    local content="$2"
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
markers.marker_write(Path(sys.argv[3]), getattr(markers, sys.argv[4]), sys.argv[5])
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "${marker_name}" "${content}" 2>/dev/null || true
}

# Presence probe — EXIT STATUS is the answer, nothing is printed.
#
# NO `2>/dev/null || true`, unlike the two above. Their result is a side effect,
# so swallowing a failure loses nothing a caller reads; this function's whole
# value IS the verdict, and a swallowed failure would become a confident answer.
# stderr stays visible so a broken helper is loud.
#
# A crash exits non-zero and therefore reads as "absent", which conflates it with
# a genuinely missing marker. Accepted deliberately: every caller so far treats
# absent as "do the thing", which is the behavior that predates the guard, so the
# degraded verdict is the safe one. A future caller for which absent is the
# DANGEROUS answer must not use this helper bare.
marker_exists() {
    local marker_name="$1"
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from pathlib import Path
import markers
sys.exit(0 if markers.marker_exists(Path(sys.argv[3]), getattr(markers, sys.argv[4])) else 1)
' "${PLUGIN_ROOT}/scripts" "${PLUGIN_ROOT}/smm" "${SMM_DIR}" "${marker_name}"
}
