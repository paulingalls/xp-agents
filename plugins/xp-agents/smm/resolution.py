#!/usr/bin/env python3
"""Resolution tracking and notification helpers.

Extracted from _append_impl.py to reduce module size and clarify boundaries.

Two sections:
  1. Event resolution tracking (pure logic, no IO)
  2. Desktop notifications for blocking questions
"""

import re
import subprocess
import sys

import event_schema
from event_schema import METADATA_KEY_RESOLVES

# ---------------------------------------------------------------------------
# Event resolution tracking (shared by materialize, retrospective, hooks)
# ---------------------------------------------------------------------------

_ID_FULL_LENGTH = 12

# Synthetic type stamped on the nested retrospective try[] entries `index_event`
# lifts into the id index. They are not real events — no such line exists in the
# log — so this type never appears on disk; it exists so consumers can tell a
# Try id apart from a top-level event id after indexing. `intent.retro_try_ids`
# reads it to scope the retro intent map to Try ids only.
RETRO_TRY_TYPE = "retro_try"


def resolve_prefix(target_id: str, by_id: dict[str, dict]) -> tuple[str, dict] | None:
    """Resolve an event ID by exact match.

    With 12-char hex IDs, exact match is the primary path. Prefix
    scanning is retained as a fallback for any IDs shorter than 12 chars.
    Returns (full_id, event) or None if not found / ambiguous.
    """
    event = by_id.get(target_id)
    if event:
        return target_id, event

    if len(target_id) >= _ID_FULL_LENGTH:
        return None

    match_id: str | None = None
    for k in by_id:
        if k.startswith(target_id):
            if match_id is not None:
                return None
            match_id = k

    if match_id is not None:
        return match_id, by_id[match_id]
    return None


def index_event(event: dict, by_id: dict[str, dict]) -> None:
    """Add one event's resolvable ids to `by_id`: its own id, plus any nested
    retrospective try-item ids (disposition events close those via
    metadata.resolves). Top-level ids win a collision — `setdefault` preserves
    them.

    Per-event rather than a pre-pass because `compute_resolutions` builds
    `by_id` incrementally: its question-answer linking looks up refs in the
    partially-built index, so an answer preceding its question must not resolve
    it. A full pre-pass would silently change that.

    Single source of truth for what a `Resolves-Event:` target may name, so the
    resolver and the unlinkable-trailer advisory cannot desync when a future
    nested-id kind is added.
    """
    event_id = event.get("id", "")
    if event_id:
        by_id[event_id] = event
    if event.get("type") != event_schema.EVENT_TYPE_RETROSPECTIVE:
        return
    for item in event.get("try", []):
        if not isinstance(item, dict):
            continue
        try_id = item.get("id")
        if not try_id:
            continue
        by_id.setdefault(
            try_id,
            {
                "id": try_id,
                "type": RETRO_TRY_TYPE,
                "content": item.get("content", ""),
                "ts": event.get("ts", ""),
                "parent_retro_id": event_id,
            },
        )


def resolvable_event_ids(events: list[dict]) -> set[str]:
    """Every id a `Resolves-Event:` / metadata.resolves target can link to.

    The advisory must consult the SAME set the resolver does, or it flags a
    valid retro-try target as dangling and fires a spurious 'the link will not
    resolve' concern. Built through `index_event`, so it cannot drift.
    """
    by_id: dict[str, dict] = {}
    for event in events:
        index_event(event, by_id)
    return set(by_id)


def compute_resolutions(events: list[dict]) -> dict:
    """Single-pass computation of question answers and event resolutions,
    followed by a multi-level cascade pass iterated to a fixed point.

    Resolution mechanism:
      - Questions: resolved by `answer` events that reference them,
        OR via `metadata.resolves` (answer events take precedence).
      - Goals, concerns, debt, decisions, assumptions: resolved via `metadata.resolves`
        array (any event with metadata.resolves: ["target-id"] resolves the target).
      - Cascade (WEAK): after the main pass, any event whose top-level
        `references` list contains a resolved id is itself marked resolved.
        MULTI-LEVEL: the cascade iterates to a fixed point, so a flag chain
        (B → A → resolved root) closes every level. Closure relays only
        through genuine flag/tracked buckets (concern/goal/debt/decision/
        assumption) — never through `other` (status/sprint) events,
        so an ephemeral status event enriched with `references` does not relay
        closure to a substantive flag that points at it (preserves the
        single-level floor; see SMM assumption d0eac70ea560).
        QUESTIONS are excluded from the cascade entirely: a question clears
        only via an answer event, metadata.resolves, or AskUserQuestion (the
        blocking-question gate), never because its `references` reach a
        resolved root — that would fabricate a customer decision.
        TERMINATION: the loop is bounded by the event count and stops at the
        fixed point (no new closures in a pass), so a pure reference cycle
        terminates with both nodes left unresolved.

    Returns dict with:
      - question_answers: dict mapping question event ID → answer event
      - concern_resolutions: dict mapping concern event ID → resolving event
      - goal_resolutions: dict mapping goal event ID → resolving event
      - debt_resolutions: dict mapping debt event ID → resolving event
      - decision_resolutions: dict mapping decision event ID → resolving event
      - assumption_resolutions: dict mapping assumption event ID → resolving event
      - other_resolutions: dict mapping any other event type ID → resolving event
      - answered_question_ids: set of answered question IDs
      - resolved_concern_ids: set of resolved concern IDs
      - resolved_goal_ids: set of resolved goal IDs
      - resolved_debt_ids: set of resolved debt IDs
      - resolved_decision_ids: set of resolved decision IDs
      - resolved_assumption_ids: set of resolved assumption IDs
      - resolved_other_ids: set of resolved other event IDs
    """
    by_id: dict[str, dict] = {}
    question_answers: dict[str, dict] = {}
    concern_resolutions: dict[str, dict] = {}
    goal_resolutions: dict[str, dict] = {}
    debt_resolutions: dict[str, dict] = {}
    decision_resolutions: dict[str, dict] = {}
    assumption_resolutions: dict[str, dict] = {}
    other_resolutions: dict[str, dict] = {}

    for event in events:
        event_id = event.get("id", "")
        # Indexes this event's own id plus any nested retrospective try[] ids,
        # so disposition events (adopt/defer/drop) can resolve them via
        # metadata.resolves. Shared with `resolvable_event_ids` — the advisory
        # in commit_handling must judge linkability against this exact index.
        # Stays inside the loop: the question-answer linking below reads the
        # partially-built `by_id`, so the incremental order is load-bearing.
        index_event(event, by_id)

        # Question-answer linking: answer events reference questions
        if event.get("type") == event_schema.EVENT_TYPE_ANSWER:
            for ref_id in event.get("references", []):
                ref_event = by_id.get(ref_id)
                if (
                    ref_event
                    and ref_event.get("type") == event_schema.EVENT_TYPE_QUESTION
                ):
                    question_answers[ref_id] = event

        # Explicit resolution via metadata.resolves
        for target_id in event.get("metadata", {}).get(METADATA_KEY_RESOLVES, []):
            resolved = resolve_prefix(target_id, by_id)
            if not resolved:
                continue
            full_id, target = resolved
            match target.get("type"):
                case event_schema.EVENT_TYPE_QUESTION:
                    # setdefault: answer events (added above) take
                    # precedence over metadata.resolves
                    question_answers.setdefault(full_id, event)
                case event_schema.EVENT_TYPE_CONCERN:
                    concern_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_GOAL:
                    goal_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_DEBT:
                    debt_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_DECISION:
                    decision_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_ASSUMPTION:
                    assumption_resolutions[full_id] = event
                case _:
                    other_resolutions[full_id] = event

    buckets = {
        event_schema.EVENT_TYPE_QUESTION: question_answers,
        event_schema.EVENT_TYPE_CONCERN: concern_resolutions,
        event_schema.EVENT_TYPE_GOAL: goal_resolutions,
        event_schema.EVENT_TYPE_DEBT: debt_resolutions,
        event_schema.EVENT_TYPE_DECISION: decision_resolutions,
        event_schema.EVENT_TYPE_ASSUMPTION: assumption_resolutions,
    }
    resolver_map: dict[str, dict] = {}
    for bucket in (*buckets.values(), other_resolutions):
        resolver_map.update(bucket)

    # Only these events can ever cascade-close, so the pass loop iterates them
    # instead of re-scanning the whole log each time. Every event excluded here
    # is a provable no-op in the loop body below: no id / already resolved
    # (skipped outright), a question (never a cascade target), or no
    # `references` (the resolver lookup yields None). Built AFTER resolver_map
    # is seeded and BEFORE the first pass; relative list order is preserved
    # because the cascade's resolver identity is order-sensitive.
    candidates: list[dict] = [
        e
        for e in events
        if e.get("id")
        and e.get("type") != event_schema.EVENT_TYPE_QUESTION
        and (e.get("references") or [])
        and e["id"] not in resolver_map
    ]
    # Tracks "entered any bucket", which is NOT the same as "in resolver_map":
    # an `other` closure is added to a bucket but deliberately never relays, so
    # it never reaches resolver_map. Pruning on resolver_map membership alone
    # would keep every `other` closure in `candidates` forever — precisely the
    # events this filtering exists to drop.
    # The set and the prune below are keyed by event id, so they rely on
    # top-level ids being unique (generate_id -> 48-bit secrets.token_hex, and
    # by_id/resolver_map are already id-keyed). The whole-log re-scan this
    # replaces re-evaluated each event object every pass; if two DISTINCT
    # top-level events ever shared an id, closing one here would prune the
    # other before it could close. Unreachable in practice, but load-bearing.
    closed: set[str] = set()

    # Bounded fixed-point cascade. range(len(events)) is the cycle guard:
    # resolver_map only grows (by >=1 each pass that sets changed), bounded by
    # the event count, so a pure reference cycle never resolves and exits via
    # changed=False. The feed-back below relays closure ONLY through genuine
    # flag/tracked chains (non-`other` buckets), never through ephemeral status
    # events enriched with `references` — preserving single-level behavior as
    # the floor (see SMM assumption d0eac70ea560).
    for _ in range(len(events)):
        changed = False
        for event in candidates:
            event_id = event["id"]
            if event_id in resolver_map:
                continue
            # Questions never cascade-close. A question clears ONLY via an
            # answer event, metadata.resolves, or AskUserQuestion (all handled
            # in the main pass above and seeded into resolver_map). Letting a
            # question close just because its `references` transitively reach a
            # resolved root would fabricate a customer decision and silently
            # drop a still-open blocking question from the open-questions nudge
            # and inflate retro questions_answered — see the blocking-question
            # gate. An answered question still *seeds* the cascade as a resolver
            # for downstream flags; it just can never be a cascade *target*.
            if event.get("type") == event_schema.EVENT_TYPE_QUESTION:
                continue
            refs = event.get("references") or []
            resolver = next(
                (resolver_map[r] for r in refs if r != event_id and r in resolver_map),
                None,
            )
            if resolver is None:
                continue
            bucket = buckets.get(event.get("type", ""), other_resolutions)
            bucket.setdefault(event_id, resolver)
            closed.add(event_id)
            if bucket is not other_resolutions:
                # Feed the newly-resolved flag/tracked event back so deeper
                # levels see it on the next pass. Skipped for `other` (status,
                # sprint, ...) so closure never relays through them.
                resolver_map[event_id] = resolver
                changed = True
        if not changed:
            break
        candidates = [e for e in candidates if e["id"] not in closed]

    return {
        "question_answers": question_answers,
        "concern_resolutions": concern_resolutions,
        "goal_resolutions": goal_resolutions,
        "debt_resolutions": debt_resolutions,
        "decision_resolutions": decision_resolutions,
        "assumption_resolutions": assumption_resolutions,
        "answered_question_ids": set(question_answers.keys()),
        "resolved_concern_ids": set(concern_resolutions.keys()),
        "resolved_goal_ids": set(goal_resolutions.keys()),
        "resolved_debt_ids": set(debt_resolutions.keys()),
        "resolved_decision_ids": set(decision_resolutions.keys()),
        "resolved_assumption_ids": set(assumption_resolutions.keys()),
        "other_resolutions": other_resolutions,
        "resolved_other_ids": set(other_resolutions.keys()),
    }


def claimed_resolved_ids(events: list[dict]) -> set[str]:
    """Every id any event CLAIMS to close, read straight off `metadata.resolves`.

    INDEX-FREE, and that is the whole point of it existing beside
    `collect_all_resolved_ids`. `compute_resolutions` can only mark a target
    resolved if `resolve_prefix` still finds the target's own event in the log —
    so once a target is archived, a closer naming it resolves NOTHING.

    That gap is fatal for any durable store of open items (`adoption_store`): the
    ids such a store remembers are precisely the ones whose events are gone, so
    pruning it on `compute_resolutions` alone is blind exactly where it must see.
    A closer would land, be archived itself (it is a transient `status`), and the
    store would go on calling a finished item open forever.

    Prefix targets and cascade closures are NOT visible here — those need the
    index. The two functions are complements, not substitutes: union them.
    """
    return {
        target
        for event in events
        for target in (event.get("metadata") or {}).get(METADATA_KEY_RESOLVES) or []
    }


def collect_all_resolved_ids(resolutions: dict) -> set[str]:
    """Union every set value at a `*_ids` key in *resolutions*.

    Single source of truth for the "what events have been resolved at all"
    question. Co-located with `compute_resolutions` so adding a new
    `*_ids` key here keeps the helper in sync automatically — the suffix
    scan picks it up. Callers: draft_summary.py, triage_preload.py,
    concern_triage.py.
    """
    resolved: set[str] = set()
    for key, value in resolutions.items():
        if key.endswith("_ids"):
            resolved |= value
    return resolved


def closed_target_ids(events: list[dict]) -> set[str]:
    """Every id the log says is finished with — the ledger's prune signal.

    The UNION of the two closure readings, because each is blind where the other
    sees, and the ledger needs both:

      * `collect_all_resolved_ids(compute_resolutions(...))` resolves through the
        id INDEX, so it alone catches prefix targets and WEAK-cascade closures
        (an adopt `decision` closes when its `references` reach a resolved root).
        But it can only resolve a target whose OWN event is still in the log.
      * `claimed_resolved_ids` reads `metadata.resolves` raw, so it sees a closer
        naming a target that was archived long ago — which is the ledger's entire
        population. This is the one that stops the resurrection: a Try dropped
        after its retrospective was archived is unindexable, so the resolver
        cannot see the drop at all, the entry would survive the drop event's own
        archival, and the Try would read as adopted forever.

    It is also exactly the set `intent._build_intent_map` treats as closed, plus
    the index-derived ids — so the reader can never call something open that the
    pruner called closed.
    """
    return collect_all_resolved_ids(compute_resolutions(events)) | claimed_resolved_ids(
        events
    )


# ---------------------------------------------------------------------------
# Desktop notification for blocking questions
# ---------------------------------------------------------------------------


def _detect_platform() -> str:
    """Return 'macos', 'linux', or 'unknown'."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _sanitize_notification(text: str) -> str:
    """Allow only safe characters and limit to 200 chars for shell use."""
    text = re.sub(r"[^a-zA-Z0-9 .,!?:;\-_()\n]", "", text)
    return text[:200]


def _notify_blocking_question(event: dict) -> None:
    """Send a desktop notification for 🔴 priority questions. Swallows all errors."""
    try:
        if event.get("type") != event_schema.EVENT_TYPE_QUESTION:
            return
        if event.get("priority") != event_schema.PRIORITY_BLOCKING:
            return

        message = _sanitize_notification(event.get("content", "Blocking question"))
        platform = _detect_platform()

        if platform == "macos":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "XP Agents"',
                ],
                timeout=5,
                capture_output=True,
            )
        elif platform == "linux":
            subprocess.run(
                ["notify-send", "XP Agents", message],
                timeout=5,
                capture_output=True,
            )
    except Exception:
        pass
