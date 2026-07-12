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

Every event built here carries a LANE TAG in `metadata.action` — one of
`retro_try_disposition` / `triage_disposition`. The two lanes name their targets
in the same `references` field, so without the tag a reader cannot tell a Try's
deferral from a debt's, and the readers that must tell them apart (smm/intent.py,
the FORCE-CLOSE gate) would have to guess from event shape. The tag is the same
deterministic-event doctrine the rest of the vocabulary follows: consumers read
`metadata.action` so structured facts are not parsed back out of prose.

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
    STATUS_ACTION_RETRO_TRY_DISPOSITION,
    STATUS_ACTION_TRIAGE_DISPOSITION,
)
from retro_history import HEX_ID_RE  # noqa: E402
from smm_schema import EVENT_ID_RE  # noqa: E402
from work_selection_filters import (  # noqa: E402
    _FORCE_CLOSE_THRESHOLD,
    _cascade_ids_filter,
    _count_prior_defers_filter,
    _force_close_message,
)


def _retro_metadata(disposition: str, **extra: str) -> dict:
    """Metadata for a retro-Try disposition: the lane tag plus the disposition.

    Every retro-lane builder routes through here so no path can ship a
    disposition without its lane tag — an untagged deferral is indistinguishable
    from a triage deferral downstream, and the FORCE-CLOSE gate has to fall back
    to counting it on faith (see `_counts_as_retro_defer`'s legacy leg).
    """
    # Literal "action" key, matching every other producer in the codebase
    # (bash_post_tool, lint_check, commit_event); `event_action` is the reader.
    return {
        "action": STATUS_ACTION_RETRO_TRY_DISPOSITION,
        METADATA_KEY_DISPOSITION: disposition,
        **extra,
    }


def build_adopt_event(agent_id: str, content: str, topic: str | None) -> dict:
    """Build the decision event for an `adopt` (and for `defer --force-adopt`).

    Still a `decision`, so `topic` stays required by the schema — a None topic
    is passed straight through to `validate_event`, which rejects it, exactly as
    before. The added
    disposition is deliberately non-terminal: `is_closing` stays False, so the
    `[refs: ...]` ids keep routing to the top-level `references` field and the
    adopted Try stays OPEN. Adoption is a promise to do the work, not evidence
    that the work landed.
    """
    return _common.make_event(
        "decision",
        agent_id,
        content,
        topic=topic,
        metadata=_retro_metadata(DISPOSITION_ADOPTED),
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
        metadata=_retro_metadata(DISPOSITION_DROPPED),
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
        return build_adopt_event(agent_id, content, force_adopt_topic)
    if force_drop:
        return _build_drop_event(load_events, agent_id, content)
    if force_defer_until:
        _validate_future_iso_date(force_defer_until)
        return _common.make_event(
            "status",
            agent_id,
            content,
            working_on=[],
            metadata=_retro_metadata(
                DISPOSITION_DEFERRED, **{METADATA_KEY_DEFER_UNTIL: force_defer_until}
            ),
        )
    event = _common.make_event(
        "status",
        agent_id,
        content,
        working_on=[],
        metadata=_retro_metadata(DISPOSITION_DEFERRED),
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

    Route the target id by evidence, mirroring extract_refs_suffix: only a drop
    is terminal, so only a drop closes the target via metadata.resolves. Adopting
    and DEFERRING both link — the target id lands in the top-level `references`
    field and the item stays OPEN.

    The deferral link is new. It reverses an earlier judgement that "carrying an
    item says nothing about it beyond 'not now'", which reasoned from a frame
    where linking WAS closing and so a link had to be earned. That frame is gone:
    linking is now strictly weaker than closing (a `status` lands in
    `other_resolutions`, which does not relay closure — resolution.py). What is
    left is that a deferral does say something durable — the user saw this item
    and chose not now — and an unlinked deferral is undetectable by construction,
    which is why the ~20 legacy triage-defers on disk are unrecoverable.
    """
    if event_id is None:
        raise ValueError(f"{action} requires --event-id")
    if not EVENT_ID_RE.match(event_id):
        raise ValueError(f"Invalid event ID format: {event_id}")
    disposition = _TRIAGE_DISPOSITIONS[action]
    metadata: dict = {
        "action": STATUS_ACTION_TRIAGE_DISPOSITION,
        METADATA_KEY_DISPOSITION: disposition,
    }
    # Deliberately if/else, not match/case: a bare NAME in a `case` is a
    # capture pattern that matches ANY value, so `case DISPOSITION_DROPPED:`
    # would route every disposition into metadata.resolves — silently
    # restoring the exact defect this routing exists to remove. Comparison
    # is what is meant here, so comparison is what is written.
    link_field: dict = {}
    if disposition == DISPOSITION_DROPPED:
        metadata[METADATA_KEY_RESOLVES] = [event_id]
    else:
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
