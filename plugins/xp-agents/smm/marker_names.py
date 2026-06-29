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
CLOSE_CYCLE_ACTIVE = ".close-cycle-active"
LINT_WARNED = ".lint-warned"
REVIEW_CADENCE = ".review-cadence"
SPRINT_RETRO_INPUT = ".sprint-retro-input.json"
CURATION_INPUT = ".curation-input.json"
COORDINATION_JSON = ".coordination.json"
COORDINATION_LOCK = ".coordination.lock"
SISTER_TEST_LAYOUT_WARN = ".sister-test-layout-warn"

QUESTION_NUDGED = ".question-nudged-{agent_id}"
TEAMMATE_REPORT = ".teammate-report-{name}.txt"
STORY_ASSIGNMENT = ".story-assignment-{name}"

SPRINT_REVIEW_INPUT_PREFIX = ".sprint-review-input."

RETROSPECTIVES_DIR = "retrospectives"

RENDER_RETRO_SIGNATURE = "# XP Retrospective \u2014 Keep / Fix / Try"
RENDER_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"
