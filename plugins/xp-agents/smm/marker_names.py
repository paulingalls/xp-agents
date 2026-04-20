"""Marker filename constants — shared across sys.path boundary.

This module contains only filename strings. It has no imports and no
dependencies, which lets both `scripts/` (via sys.path insertion) and
`skills/*/scripts/` (which only add `smm/` to sys.path) reference the
same marker names without duplication.

The full marker infrastructure (MarkerDef, marker_read, marker_write,
marker_consume) lives in `scripts/markers.py` which imports these
constants. Skill scripts that need to read/write marker files do so
directly via pathlib using these constants.
"""

KICKOFF = ".needs-kickoff"
NEEDS_SPRINT = ".needs-sprint"
ACCEPT = ".accept"
SECURITY_TRIAGED = ".security-triaged-{agent_id}"
PLAN_AWAITING_REVIEW = ".plan-awaiting-review"
QUESTION_GATE = ".question-gate"
ASKING_USER = ".asking-user"
NEEDS_EXECUTION_PLAN = ".needs-execution-plan"
NEEDS_SYSTEM_CONTEXT = ".needs-system-context"
ASSIGN_PENDING = ".assign-pending"
NEEDS_HOUSEKEEPING = ".needs-housekeeping"
PENDING_RENDER_RETRO = ".pending-render-retro-{agent_id}"
PENDING_RENDER_SMM = ".pending-render-smm-{agent_id}"
REVIEW_FINGERPRINT = ".review-fingerprint-{agent_id}"

RENDER_RETRO_SIGNATURE = "# XP Retrospective \u2014 Keep / Fix / Try"
RENDER_SMM_SIGNATURE = "# Shared Mental Model \u2014 Curated View"

# Plain-text phrases the echo-gate checks for — deliberately loose.
# All phrases in the tuple must appear in the assistant's text for the
# marker to clear. No markdown prefix, no em-dash required: the gate is
# a "did you forget?" reminder, not a format enforcer. Agents that
# paraphrase the heading, drop the `#`, or use an ASCII dash still clear.
RENDER_RETRO_PHRASES = ("XP Retrospective", "Keep / Fix / Try")
RENDER_SMM_PHRASES = ("Shared Mental Model", "Curated View")
