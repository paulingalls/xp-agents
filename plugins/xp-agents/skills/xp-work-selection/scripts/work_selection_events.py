#!/usr/bin/env python3
"""Event builders for the adopt/defer/drop decision path.

Each builder turns one CLI action into the event dict that action warrants,
consulting the pure filters next door when it needs history (cascade ids,
prior-defer count). Extracted from work_selection_decide.py when it approached
the 500-line cap; the orchestration (argparse, budget truncation, validation,
append) stays there and re-exports these names, so callers and tests are
unaffected by the move.

`load_events` is always run()'s memoized accessor, invoked lazily — a builder
that needs no history never touches disk.

Names keep their leading underscore: they are internal to the work-selection
scripts, not a public surface — the trio of modules is one unit.
"""

import datetime
import sys
from collections.abc import Callable
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
from event_builder import REFERENCES_KEY, merge_resolves  # noqa: E402
from event_schema import (  # noqa: E402
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    METADATA_KEY_DEFER_UNTIL,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
)
from retro_history import HEX_ID_RE  # noqa: E402
from smm_schema import EVENT_ID_RE  # noqa: E402
from work_selection_filters import (  # noqa: E402
    _FORCE_CLOSE_THRESHOLD,
    _cascade_ids_filter,
    _count_prior_defers_filter,
    _force_close_message,
)


def _validate_future_iso_date(value: str) -> None:
    """Validate YYYY-MM-DD format AND require date >= today.

    The today-floor closes a laundering vector: without it, --force-defer-with-date
    accepts past dates and silently slips a stale Try past the FORCE-CLOSE gate.
    """
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(
            f"Invalid date for --force-defer-with-date: {value} (expected YYYY-MM-DD)"
        ) from e
    if parsed < datetime.date.today():
        raise ValueError(
            f"--force-defer-with-date must be >= today; got {value}. "
            "Past dates would silently launder the Try past the FORCE-CLOSE gate."
        )


def _build_drop_event(
    load_events: Callable[[], list[dict]], agent_id: str, content: str
) -> dict:
    """Build the status/dropped event used by both `drop` and `defer --force-drop`.

    Cascade: scan the post-suffix-strip content for 12+ hex IDs. Any that
    resolve to an existing debt/concern/discovery event (the same set as
    PROBE_RESOLVABLE_TYPES) are unioned into `metadata.resolves` — so
    dropping a Try also closes the root issue the Try is about, preventing
    the retro agent from re-proposing a fresh Try every session.

    `load_events` is run()'s memoized accessor — invoked lazily only when
    hex tokens are present, preserving the "no-tokens skips disk read"
    perf guard. Once called by any filter, the same list backs subsequent
    filters on this invocation.
    """
    event = _common.make_event(
        "status",
        agent_id,
        content,
        working_on=[],
        metadata={METADATA_KEY_DISPOSITION: DISPOSITION_DROPPED},
    )
    tokens = set(HEX_ID_RE.findall(event["content"]))
    if not tokens:
        return event
    cascade_ids = _cascade_ids_filter(load_events(), tokens)
    if cascade_ids:
        merge_resolves(event, cascade_ids)
    return event


def _build_defer_event(
    load_events: Callable[[], list[dict]],
    agent_id: str,
    content: str,
    force_adopt_topic: str | None,
    force_drop: bool,
    force_defer_until: str | None,
) -> dict:
    """Build the event for a `defer` invocation, applying the FORCE-CLOSE gate.

    `load_events` is run()'s memoized accessor — only invoked when refs
    are present (gate read) or when force_drop triggers the cascade scan.

    Force flags are mutually exclusive and short-circuit the gate by selecting
    the outcome event directly:
      --force-adopt → decision event
      --force-drop  → status event, disposition=dropped
      --force-defer-with-date → status event, disposition=deferred + defer_until
    With no force flag, builds the deferred status event and refuses if the
    Try has been deferred at or above _FORCE_CLOSE_THRESHOLD times.
    """
    if sum([bool(force_adopt_topic), force_drop, bool(force_defer_until)]) > 1:
        raise ValueError(
            "force flags are mutually exclusive: pick at most one of "
            "--force-adopt, --force-drop, --force-defer-with-date"
        )
    if force_adopt_topic:
        return _common.make_event(
            "decision",
            agent_id,
            content,
            topic=force_adopt_topic,
        )
    if force_drop:
        return _build_drop_event(load_events, agent_id, content)
    if force_defer_until:
        _validate_future_iso_date(force_defer_until)
        return _common.make_event(
            "status",
            agent_id,
            content,
            working_on=[],
            metadata={
                METADATA_KEY_DISPOSITION: DISPOSITION_DEFERRED,
                METADATA_KEY_DEFER_UNTIL: force_defer_until,
            },
        )
    event = _common.make_event(
        "status",
        agent_id,
        content,
        working_on=[],
        metadata={METADATA_KEY_DISPOSITION: DISPOSITION_DEFERRED},
    )
    # A deferral is an intent event, so the suffix ids landed in `references`.
    refs = event.get(REFERENCES_KEY) or []
    if refs:
        prior = _count_prior_defers_filter(load_events(), refs)
        if prior >= _FORCE_CLOSE_THRESHOLD:
            raise ValueError(_force_close_message(refs, prior))
    return event


_TRIAGE_DISPOSITIONS = {
    "triage-adopt": DISPOSITION_ADOPTED,
    "triage-defer": DISPOSITION_DEFERRED,
    "triage-drop": DISPOSITION_DROPPED,
}


def _build_triage_event(
    load_events: Callable[[], list[dict]],
    agent_id: str,
    action: str,
    event_id: str | None,
) -> dict:
    """Build the status event for a triage-adopt / -defer / -drop invocation.

    Route the target id by evidence, mirroring extract_refs_suffix:
    only a drop is terminal, so only a drop closes the target. Adopting
    means taking the work ON — it links, and the target stays open
    until the work lands. Deferring records neither: carrying an item
    says nothing about it beyond "not now".
    """
    if event_id is None:
        raise ValueError(f"{action} requires --event-id")
    if not EVENT_ID_RE.match(event_id):
        raise ValueError(f"Invalid event ID format: {event_id}")
    disposition = _TRIAGE_DISPOSITIONS[action]
    metadata: dict = {METADATA_KEY_DISPOSITION: disposition}
    # Deliberately if/elif, not match/case: a bare NAME in a `case` is a
    # capture pattern that matches ANY value, so `case DISPOSITION_DROPPED:`
    # would route every disposition into metadata.resolves — silently
    # restoring the exact defect this routing exists to remove. Comparison
    # is what is meant here, so comparison is what is written.
    link_field: dict = {}
    if disposition == DISPOSITION_DROPPED:
        metadata[METADATA_KEY_RESOLVES] = [event_id]
    elif disposition == DISPOSITION_ADOPTED:
        link_field[REFERENCES_KEY] = [event_id]
    # Inline a snippet of the target event's content so cross-session
    # drop memory (retro_metrics.dropped_tries_recent) carries the
    # topic forward — opaque "Triage: dropped <id>" content defeats
    # the retro agent's LLM topic-match safety net. Falls back to
    # the terse form when target lookup fails (stale or archived id).
    target = next(
        (e for e in load_events() if e.get("id") == event_id),
        None,
    )
    target_content = (target or {}).get("content", "")
    triage_content = (
        f"Triage: {disposition} {event_id[:8]} — {target_content}"
        if target_content
        else f"Triage: {disposition} {event_id[:8]}"
    )
    return _common.make_event(
        "status",
        agent_id,
        triage_content,
        working_on=[],
        metadata=metadata,
        **link_field,
    )
