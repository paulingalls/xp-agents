#!/usr/bin/env python3
"""Metadata vocabulary: STATUS_ACTION_*, METADATA_KEY_*, DISPOSITION_*,
RETRO_ACTION_*, CONCERN_KIND_* string constants, plus the accessors and
predicates that read them off an event (`event_action`, `event_disposition`,
`is_closing`, `intent_disposition`, `is_retro_lane`, `is_triage_lane`).

Extracted from event_schema.py (split-shim convention 91fcf9b8744d) when
event_schema.py crossed 500 lines. The convention is that event_schema.py
re-exports every public name here, so callers keep writing
`from event_schema import STATUS_ACTION_*` without churn.

CAVEAT, so the next reader is not misled: the shim is NOT presently a complete
mirror. The ten STATUS_ACTION_RETIRE_* / STATUS_ACTION_EDIT_* names are absent
from it, and their only consumers (system_context_retire_cli,
system_context_edit_cli) import them from THIS module directly, so nothing is
broken today — but `from event_schema import STATUS_ACTION_RETIRE_MODULE` would
raise ImportError, which is not what the convention above advertises. Whether
to close the gap or to narrow the convention is an open question (see the SMM);
either way, do not read the gap as license to skip a re-export.

Zero dependencies on other event_schema symbols — nothing here imports from
event_schema — so this module has no circular-import risk with it.
"""

# Status event metadata.action discriminators — used by cascading gates
# to identify specific lifecycle events without scanning content strings.
STATUS_ACTION_ITERATION_COMPLETE = "iteration_complete"
STATUS_ACTION_SPRINT_RETRO_DONE = "sprint_retro_done"

# Review-cycle lifecycle actions — vocabulary for the deterministic-event
# doctrine. The sole producer is review_cycle_done.py, which
# sets metadata.action to one of these values so consumers (retro_metrics,
# bash_post_tool) can detect skill completions without regex-matching
# LLM-authored content.
STATUS_ACTION_SIMPLIFY_COMPLETE = "simplify_complete"
STATUS_ACTION_QR_COMPLETE = "qr_complete"
STATUS_ACTION_SECURITY_COMPLETE = "security_complete"
STATUS_ACTION_PLAN_REVIEWED = "plan_reviewed"
STATUS_ACTION_ASSIGN_COMPLETE = "assign_complete"
STATUS_ACTION_HOUSEKEEPING_COMPLETE = "housekeeping_complete"

# Emitted by xp-{sprint,free,plan}-close preloads (not story-close — it has
# no Step 4 security review). Sourced by retro_metrics.security_close_ran
# to scope the security_checks=0 Courage rule to security-bearing close
# modes. Carries close_mode + close_cycle_id in metadata.
STATUS_ACTION_CLOSE_STARTED = "close_started"

# Tool-action lifecycle vocabulary — extends the review-cycle doctrine
# above with structured tool events. Each constant is emitted by exactly
# one hook; consumers read
# metadata.action so structured fields (files, exit_code, framework, etc.)
# are not parsed back out of LLM-authored content. Producer map:
#   STATUS_ACTION_FILE_WRITE        — post_tool_use.py (Write/Edit/MultiEdit)
#   STATUS_ACTION_TEST_RUN_COMPLETE — bash_post_tool.py (test command success)
#   STATUS_ACTION_LINT_RESOLVED     — lint_resolution.py (lint resolved on commit)
#   STATUS_ACTION_BASH_FAILED       — bash_failure.py (Bash exit non-zero)
#   STATUS_ACTION_COMMIT_SUCCESS    — bash_post_tool.py (git commit, type=commit)
STATUS_ACTION_FILE_WRITE = "file_write"
STATUS_ACTION_TEST_RUN_COMPLETE = "test_run_complete"
STATUS_ACTION_LINT_RESOLVED = "lint_resolved"
STATUS_ACTION_BASH_FAILED = "bash_failed"
STATUS_ACTION_COMMIT_SUCCESS = "commit_success"

# Subagent + plan lifecycle vocabulary — extends the tool-action wave
# with subagent stop signals. Closes the cleanup window opened by the
# prior tool-action vocabulary. Producer map:
#   STATUS_ACTION_SUBAGENT_COMPLETE     — subagent_stop.py (every subagent)
#   STATUS_ACTION_PLAN_COMPLETED        — subagent_stop.py (Plan subagent stop)
#   STATUS_ACTION_PLAN_AWAITING_REVIEW  — subagent_stop.py (Plan subagent gate)
#   STATUS_ACTION_PLAN_EXITED           — post_tool_exit_plan.py (ExitPlanMode)
STATUS_ACTION_SUBAGENT_COMPLETE = "subagent_complete"
STATUS_ACTION_PLAN_COMPLETED = "plan_completed"
STATUS_ACTION_PLAN_AWAITING_REVIEW = "plan_awaiting_review"
STATUS_ACTION_PLAN_EXITED = "plan_exited"

# Step 5c (close skills) — concern classification per finding.
# Producer: story-close + free-close at Step 5c (LLM via append.sh).
# Consumer: count-classifications subcommand for the Step 6 auto-merge
# gate; retro tooling for prediction-loop validation.
# Companion metadata fields the producer also sets:
#   metadata.route       — "fix" | "ask" — which dispatch route the LLM took.
#   metadata.category    — classification vocabulary (lint, test_failure, ...).
#   metadata.concern_id  — the 12-hex ID of the concern being classified.
STATUS_ACTION_CONCERN_CLASSIFY = "concern_classify"

# Question-close (won't-fix) discriminator. Producer: smm_cli question close
# --won-fix. Consumer: question-aging tooling, which already treats this
# metadata combination (action=question_close + disposition=wont_fix +
# resolves=[Q]) as a terminal disposition via metadata.resolves alone.
STATUS_ACTION_QUESTION_CLOSE = "question_close"

# End-of-session bulk-drop discriminator. Producer: xp-end-session skill
# Step 3 (LLM-judged auto-resolve of MAYBE_ADDRESSED concerns/debts).
# Companion metadata: METADATA_KEY_RESOLVES (canonical STRONG link to the
# concern/debt being closed) + METADATA_KEY_RESOLVED_BY_COMMITS (audit
# trail of which commit IDs informed the auto-judge). Consumer: retro
# tooling distinguishes end-session bulk drops from organic resolutions.
STATUS_ACTION_END_SESSION_DROP = "end_session_drop"

# system_context_cli.py retire-* subcommands. Producer: system-context-cli
# (non-hook). Each retire-X CLI removes one entry from a capped list and
# emits a status event so curation actions are traceable. Companion
# metadata: kind (singular, e.g., "principle") + identifier (topic/name
# for by-key fields; resolved entry text for convention substring).
STATUS_ACTION_RETIRE_PRINCIPLE = "retire_principle"
STATUS_ACTION_RETIRE_MODULE = "retire_module"
STATUS_ACTION_RETIRE_CONVENTION = "retire_convention"
STATUS_ACTION_RETIRE_PROJECT_SPECIFIC = "retire_project_specific"
STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE = "retire_acceptance_surface"

# system_context_cli.py edit-* subcommands. Producer: system-context-cli
# (non-hook). Each edit-X CLI patches one entry in a capped list and emits
# a status event for traceability. Companion metadata: kind (singular) +
# identifier (lookup key) + patched_keys (list of fields that changed; for
# edit_convention this is always [] since conventions are bare strings and
# the whole value is replaced rather than per-key patched).
STATUS_ACTION_EDIT_PRINCIPLE = "edit_principle"
STATUS_ACTION_EDIT_MODULE = "edit_module"
STATUS_ACTION_EDIT_CONVENTION = "edit_convention"
STATUS_ACTION_EDIT_PROJECT_SPECIFIC = "edit_project_specific"
STATUS_ACTION_EDIT_ACCEPTANCE_SURFACE = "edit_acceptance_surface"


# Adopt/defer/drop lifecycle, one constant per LANE. Producer:
# work_selection_decide — the retro-Try lane (`adopt`/`defer`/`drop`) and the
# triage lane (`triage-adopt`/`-defer`/`-drop`). Consumer: smm/intent.py.
#
# The lane tag is what makes the intent link readable. Both lanes name their
# target in the same top-level `references` field, so "id appears in references"
# cannot by itself mean "adopted" — an adopting event's reference bag ALSO holds
# the debt/concern ids the Try is merely ABOUT, and plenty of events reference an
# id for reasons that are the opposite of adoption (an auto-raised "stale
# question" concern references the question it is complaining about). Reading
# metadata.action first scopes the question to one lane's own writer, which is
# the same reason the rest of this vocabulary exists: consumers read
# metadata.action so structured fields are not parsed back out of LLM-authored
# content.
#
# Carried on a `decision` for a retro adoption and on a `status` for every other
# adopt/defer/drop — the STATUS_ACTION_ prefix names the vocabulary family, not
# a constraint on the event type.
STATUS_ACTION_RETRO_TRY_DISPOSITION = "retro_try_disposition"
STATUS_ACTION_TRIAGE_DISPOSITION = "triage_disposition"


def event_action(event: dict) -> str | None:
    """Return event.metadata.action, or None when absent.

    Centralized accessor so consumers don't repeat the
    `e.get("metadata", {}).get("action")` pattern (which also allocates a
    fresh empty dict on every miss). Returns None for legacy events without
    metadata or without the action discriminator.
    """
    metadata = event.get("metadata")
    if not metadata:
        return None
    return metadata.get("action")


def is_retro_lane(event: dict) -> bool:
    """True when *event* belongs to the retro-Try lane — its tag names that
    lane, or it carries no tag at all.

    The UNTAGGED leg is what makes this a lane gate rather than a tag test. The
    tag is newer than the events: every disposition written before it landed
    carries no `metadata.action`, and a bare `tag == retro` test would exclude
    all of them — disarming the FORCE-CLOSE gate on precisely the long-carried
    Tries it exists to catch, and hiding old adoptions from the housekeeper.
    Untagged does NOT mean "retro" as a fact about the writer; it means "the
    tag cannot answer, fall through to the reader's own legacy rule". Each
    caller supplies that rule (a topic prefix, a disposition set) — this gate
    only says the lane tag does not RULE THE EVENT OUT.

    Callers keep their own disposition set. This is deliberately only the LANE
    half of the question: `intent_disposition` is blind to `dropped` (a drop
    closes via metadata.resolves, which resolution.py owns), so a reader whose
    bucket must include drops — the housekeeper's "Deferred / Dropped" — has to
    read `metadata.disposition` itself. Folding a disposition check in here
    would silently delete retro drops from that bucket.
    """
    tag = event_action(event)
    return tag is None or tag == STATUS_ACTION_RETRO_TRY_DISPOSITION


def is_triage_lane(event: dict) -> bool:
    """True when *event*'s tag names the triage lane (a debt/concern/question
    disposition, NOT a retro Try).

    No untagged leg, and the asymmetry with `is_retro_lane` is a fact about the
    log rather than an oversight: a legacy triage-defer linked NOTHING, so it
    carries no id to read and no rule can recover it (see smm/intent.py). An
    untagged event is therefore never admitted here — it falls to the retro
    lane, where it can at least be judged by a legacy rule.
    """
    return event_action(event) == STATUS_ACTION_TRIAGE_DISPOSITION


# Cross-module metadata keys. Centralized here so producer and consumer
# cannot drift on the spelling.
#   METADATA_KEY_RESOLVES       — STRONG resolution link: event IDs this
#                                 event closes. Shape: list[str] of
#                                 12-hex-char IDs (validate_event rejects
#                                 scalars; resolution.py iterates the list).
#                                 Written by bash_post_tool, concerns,
#                                 and work_selection_decide; read by
#                                 pre_tool_bash, retrospective,
#                                 materialize, resolution.
#   METADATA_KEY_COMMIT_HASH    — git HEAD hash recorded on commit events
#                                 (bash_post_tool.py).
#   METADATA_KEY_RESOLVED_BY_COMMITS — commit event IDs that informed an
#                                 end-session auto-resolve decision (audit
#                                 trail; orthogonal to RESOLVES which is the
#                                 STRONG link). Producer: xp-end-session
#                                 status events with action=end_session_drop.
METADATA_KEY_RESOLVES = "resolves"
METADATA_KEY_SUPERSEDES = "supersedes"
METADATA_KEY_COMMIT_HASH = "commit_hash"
METADATA_KEY_RESOLVED_BY_COMMITS = "resolved_by_commits"

# Concern metadata.kind discriminator vocabulary. Centralized so producer
# (close_cycle_stop_gate hook) and consumer (retros, integration tests)
# can't drift on the spelling. Pattern matches STATUS_ACTION_* — a small
# string vocab named at module level, not inlined.
CONCERN_KIND_CLOSE_CYCLE_BYPASS = "close_cycle_bypass"

# tdd_red: producer (bash_post_tool) tags test_run_complete events when
# the prior commit was test-only (RED step in TDD); consumer
# (work_signals) skips them from consecutive_failures so legitimate
# red TDD doesn't surface as a regression streak.
METADATA_KEY_TDD_RED = "tdd_red"
METADATA_KEY_DISPOSITION = "disposition"
METADATA_KEY_CLOSE_MODE = "close_mode"
METADATA_KEY_CLOSE_CYCLE_ID = "close_cycle_id"
# Set on a status event with disposition=deferred when the user forces a
# defer past the FORCE-CLOSE gate via --force-defer-with-date; YYYY-MM-DD.
METADATA_KEY_DEFER_UNTIL = "defer_until"

# Stale-concern sweep (session_start._sweep_stale_concerns) flag-concern keys.
# Carried on a NEW concern event with references=[orig_id]; the WEAK cascade
# (resolution.compute_resolutions) closes the flag when orig_id resolves.
# Producer: the SessionStart fresh-start block (re-homed from session_end in
# M3, counting session_started anchors). Consumer: the sweep itself
# (idempotency check) + retro Fix-lens (xp-retrospective surfaces flagged
# concerns for human triage).
METADATA_KEY_FLAGGED_STALE = "flagged_stale"
METADATA_KEY_STALE_SESSION_COUNT = "stale_session_count"

# Retro Try disposition values written to metadata.disposition by
# work_selection_decide (adopt/defer/drop) and read by retro_history,
# subagent_start. Centralized to prevent producer/consumer drift.
DISPOSITION_ADOPTED = "adopted"
DISPOSITION_DEFERRED = "deferred"
DISPOSITION_DROPPED = "dropped"
# question close --won-fix disposition. Paired with
# STATUS_ACTION_QUESTION_CLOSE on a status event resolving a question id
# via metadata.resolves.
DISPOSITION_WONT_FIX = "wont_fix"

# The dispositions that constitute terminal disposition of a target: the
# writer is done with it and nobody will come back to it. Only these may
# close a target via metadata.resolves. `adopted` and `deferred` are the
# non-terminal ones — they record intent (work taken on / work carried),
# and an event that records intent must never close the item that verifies
# the work actually landed.
_TERMINAL_DISPOSITIONS = frozenset({DISPOSITION_DROPPED, DISPOSITION_WONT_FIX})

# Every disposition the writers emit, and the INTENT set derived from it by
# negation — the non-terminal dispositions, where the writer says something
# durable about the target (it was taken on / it was carried) while leaving it
# OPEN. Derived rather than re-listed: a hand-written second literal is exactly
# how the closing and non-closing legs drift back apart, and `is_closing`'s
# contract already promises this set is the complement.
_ALL_DISPOSITIONS = frozenset(
    {
        DISPOSITION_ADOPTED,
        DISPOSITION_DEFERRED,
        DISPOSITION_DROPPED,
        DISPOSITION_WONT_FIX,
    }
)
_INTENT_DISPOSITIONS = _ALL_DISPOSITIONS - _TERMINAL_DISPOSITIONS


def event_disposition(event: dict) -> str | None:
    """Return event.metadata.disposition, or None when absent.

    The sibling of `event_action` for the other half of the lane vocabulary: a
    lane tag says WHICH writer wrote the event, a disposition says WHAT it did
    to its target. Centralized for the same reason — consumers should not
    repeat `e.get("metadata", {}).get("disposition")`, which re-derives the
    spelling at every site and allocates a fresh empty dict on every miss.

    Returns the RAW disposition, terminal values included. That is the whole
    difference from `intent_disposition`, which is deliberately blind to
    `dropped` (a drop closes via metadata.resolves). A reader whose bucket
    spans BOTH intent and closure — the housekeeper's "Deferred / Dropped" —
    needs the raw value, and reaching for `intent_disposition` there would
    silently delete the drops. Reach for this one when the bucket is yours to
    define; reach for `intent_disposition` when the question is "does this
    event leave its target open".
    """
    metadata = event.get("metadata")
    if not metadata:
        return None
    return metadata.get(METADATA_KEY_DISPOSITION)


def is_closing(event: dict) -> bool:
    """True when *event* carries a terminal disposition, i.e. it is evidence
    that its target is finished with rather than merely referenced.

    Closing is a property of the disposition, NOT of the event type: a status
    event can be either, and a `decision` never is. Single source of truth for
    both directions of the split — the writer routes suffix-derived ids to
    metadata.resolves (closing) or `references` (intent) on this predicate, and
    consumers that need the NON-terminal set derive it by negation. A
    re-derived second copy is how those two legs drift back apart.
    """
    metadata = event.get("metadata")
    if not metadata:
        return False
    return metadata.get(METADATA_KEY_DISPOSITION) in _TERMINAL_DISPOSITIONS


def intent_disposition(event: dict) -> str | None:
    """The event's NON-terminal disposition (`adopted` / `deferred`), or None
    when it carries none — the exact mirror of `is_closing`, and the predicate
    that decides whether an event records intent about its target.

    Returns the disposition rather than a bool because every caller needs to
    know WHICH intent was recorded, not merely that one was: adopted and
    deferred read differently downstream (an adopted item is being worked, a
    deferred one is being carried and its defer count feeds the FORCE-CLOSE
    gate). A terminal disposition returns None — that is `is_closing`'s
    question, and `metadata.resolves` is where its answer is written.
    """
    metadata = event.get("metadata")
    if not metadata:
        return None
    disposition = metadata.get(METADATA_KEY_DISPOSITION)
    return disposition if disposition in _INTENT_DISPOSITIONS else None


# Retrospective event metadata.action discriminators — distinguish session
# retros from sprint retros so the session-start watermark scanner only
# advances on session retros. Without this, a sprint retro at end of session
# poisons the next session's retro detection.
RETRO_ACTION_SESSION_DONE = "session_retro_done"
RETRO_ACTION_SPRINT_DONE = "sprint_retro_done"
