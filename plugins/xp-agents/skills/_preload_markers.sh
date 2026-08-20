#!/bin/bash
# Marker helpers for preloads — thin wrappers over scripts/markers.py.
#
# Extracted from _preload_base.sh when that file crossed its 500-line cap.
# Sourced by _preload_base.sh, so every preload gets these transitively with no
# call-site changes. Not executable on its own: it relies on PLUGIN_ROOT and
# SMM_DIR being set by the base.
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
#
# XP_PRELOAD_UNVERIFIED_INVOCATION=1 says the hook could not prove this run
# belongs to a real invocation. It is set on the second harness's read leg,
# where a skill is loaded BY reading its body and a plain `cat` is therefore
# indistinguishable from an invocation. The two mutating helpers answer it
# DIFFERENTLY, and the asymmetry is the whole point:
#
#   write_marker  -> SKIP. Arming a gate for an invocation that may not be
#                    happening is pure harm and has no upside: a `cat` of a
#                    close skill's body would arm the close Stop gate with no
#                    close running, and nothing would disarm it.
#
#   consume_marker -> PROCEED, deliberately, and this is the unhappy half.
#                    Spending a gate on a read is a real defect (a `cat` of
#                    xp-accept/SKILL.md discharges the accept gate, and the next
#                    `update-story done` passes with acceptance never verified).
#                    But skipping is WORSE for the one marker that matters:
#                    ACCEPT is armed by the Write gate and this consume is its
#                    ONLY discharge — see the comment at pre_tool_bash.py's
#                    mark-done gate — so skipping wedges `update-story done`
#                    permanently on that harness. Both directions are wrong,
#                    which means the fix is a SECOND discharge for that gate,
#                    not a choice here. Until then this helper keeps the usable
#                    error over the unusable one, out loud rather than by
#                    omission.
#
# PLAN_AWAITING_REVIEW, the only other consume in any preload, does have its
# real discharge elsewhere (the reviewer's SubagentStop), so it would be safe to
# skip — but one helper cannot skip for one caller and not another without
# taking a marker name argument it does not need. Left uniform.

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
    # See the header: arming on an unproven invocation has no upside.
    if [ -n "${XP_PRELOAD_UNVERIFIED_INVOCATION:-}" ]; then
        return 0
    fi
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
