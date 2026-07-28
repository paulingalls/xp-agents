"""Marker filename constants and rendered-output H1 headings.

The marker constants are filename strings used across the sys.path
boundary. The module has no imports so both `scripts/` (via sys.path
insertion) and `skills/*/scripts/` (which only add `smm/` to sys.path)
can reference the same marker names. The full marker infrastructure
(MarkerDef, marker_read, marker_write, marker_consume) lives in
`scripts/markers.py` which imports these constants.

The RENDER_*_SIGNATURE constants are the H1 headings emitted by
`smm_cli.py render` and `retro_cli.py render` at the top of their
markdown output.
"""

KICKOFF = ".needs-kickoff"
NEEDS_SPRINT = ".needs-sprint"
ACCEPT = ".accept"
ACCEPT_IN_FLIGHT = ".accept-in-flight"
PLAN_AWAITING_REVIEW = ".plan-awaiting-review"
QUESTION_GATE = ".question-gate"
ASKING_USER = ".asking-user"
NEEDS_EXECUTION_PLAN = ".needs-execution-plan"
NEEDS_SYSTEM_CONTEXT = ".needs-system-context"
ASSIGN_PENDING = ".assign-pending"
NEEDS_HOUSEKEEPING = ".needs-housekeeping"
# Written when the housekeeper subagent STARTS, consumed when it stops. Lets
# the Stop gate tell "running right now" from "never invoked" — the harness
# backgrounds Agent-tool subagents, so without it the two look identical.
# Session-suffixed in the HOOK_HEARTBEAT style; see
# markers.housekeeping_in_flight_marker.
HOUSEKEEPING_IN_FLIGHT = ".housekeeping-in-flight"
CLOSE_CYCLE_ACTIVE = ".close-cycle-active"
LINT_WARNED = ".lint-warned"
REVIEW_CADENCE = ".review-cadence"
SPRINT_RETRO_INPUT = ".sprint-retro-input.json"
CURATION_INPUT = ".curation-input.json"
COORDINATION_JSON = ".coordination.json"
COORDINATION_LOCK = ".coordination.lock"
SISTER_TEST_LAYOUT_WARN = ".sister-test-layout-warn"
TEAMMATE_CONFIG = ".teammate-config"
HOOK_HEARTBEAT = ".hook-heartbeat"

QUESTION_NUDGED = ".question-nudged-{agent_id}"
TEAMMATE_REPORT = ".teammate-report-{name}.txt"
# Verbatim capture of a teammate stream that produced no result event. `.log`,
# not `.jsonl`: the capture may hold non-JSON spawn-side text alongside
# stream-json lines, so the name promises no format.
TEAMMATE_STREAM_DUMP = ".teammate-stream-{name}.log"
STORY_ASSIGNMENT = ".story-assignment-{name}"
# Lifetime-scoped: written by spawn_teammate --in-place only for the duration
# of the in-place child run, gated on by commit_handling before it trusts the
# leaky XP_TEAMMATE_NAME env for attribution.
IN_PLACE_ACTIVE = ".in-place-active-{name}"

# The two in-place LOCKS. Neither may ever match IN_PLACE_ACTIVE's reap glob
# (".in-place-active-*") — a lock file caught by that glob would be probed as if
# it were a marker. That is why the holder lock is ".in-place-holder-", not
# ".in-place-active-...lock".
#
# IN_PLACE_DOOR_LOCK — one per SMM dir, held for MICROSECONDS by every door that
# takes a holder lock it does not intend to keep (the reap proving death, the
# teardown releasing). Without it, such a transient hold is indistinguishable to
# a concurrent claimant from a live teammate's.
#
# IN_PLACE_HOLDER — one per name, taken LOCK_NB by the supervisor and held for
# the WHOLE episode. Its being held IS the liveness verdict: the kernel releases
# it when the supervisor dies, however it dies — which no pid bookkeeping can
# promise, since a pid can be recycled.
IN_PLACE_DOOR_LOCK = ".in-place.lock"
IN_PLACE_HOLDER = ".in-place-holder-{name}.lock"

SPRINT_REVIEW_INPUT_PREFIX = ".sprint-review-input."

RETROSPECTIVES_DIR = "retrospectives"

RENDER_RETRO_SIGNATURE = "# XP Retrospective \u2014 Keep / Fix / Try"
RENDER_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"
