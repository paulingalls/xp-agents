#!/usr/bin/env python3
"""Adopt / defer / drop retro Try items, wiring the refs suffix by evidence.

Parses the `[refs: id1, id2]` suffix produced by the preload's Try-item
renderer and persists the correct event shape, so the LLM no longer has
to craft `--metadata` JSON by hand (a discipline that failed four retros
in a row).

The refs land in the link field the action's own evidence warrants (see
event_builder.extract_refs_suffix): only a terminal disposition closes its
target via metadata.resolves. Adopting or deferring records INTENT, and names
the target in the top-level `references` field instead — taking work on must
not close the item that verifies the work actually landed.

Subcommands:
  adopt  → decision event with topic + references
  defer  → status event, disposition=deferred, references, working_on=[]
  drop   → status event, disposition=dropped, metadata.resolves, working_on=[]

FORCE-CLOSE gate: a plain `defer` is refused once a Try has been deferred
3+ times (carrying it further is dishonest). The caller must escape with
--force-adopt <topic>, --force-drop, or --force-defer-with-date <YYYY-MM-DD>.
"""

import argparse
import datetime
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import identity  # noqa: E402
from event_builder import REFERENCES_KEY, merge_resolves  # noqa: E402
from event_schema import (  # noqa: E402
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    METADATA_KEY_DEFER_UNTIL,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
    get_required_budget,
    validate_event,
)
from retro_history import HEX_ID_RE  # noqa: E402
from smm_schema import EVENT_ID_RE  # noqa: E402

# Pure filters live next door (size cap); re-exported so callers and tests
# keep importing them from here.
from work_selection_filters import (  # noqa: E402
    _FORCE_CLOSE_THRESHOLD,
    _cascade_ids_filter,
    _count_prior_defers_filter,
    _force_close_message,
)

_WATERMARK_ID = "work-selection-decide"

# Convention topics emitted on force-drop are prefixed to prevent
# collision with retro-try-<slug> adoption topics. The rest of the slug
# must be kebab-case so housekeeping + topic-collision detection stay
# stable.
_CONVENTION_TOPIC_PREFIX = "retro-drop-"
_KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")


def _validate_convention_args(
    action: str,
    force_drop: bool,
    topic: str | None,
    content: str | None,
) -> None:
    """Validate convention emission preconditions.

    Both flags None → no convention (no-op). Exactly one set → error.
    Both set → require action="defer" AND force_drop=True, plus topic
    must carry the retro-drop- prefix with a kebab-case slug.
    """
    if topic is None and content is None:
        return
    if topic is None or content is None:
        raise ValueError(
            "--record-convention-topic and --record-convention-content "
            "must be passed together"
        )
    if not (action == "defer" and force_drop):
        raise ValueError(
            "--record-convention-* flags are only honored with `defer --force-drop`"
        )
    if not topic.startswith(_CONVENTION_TOPIC_PREFIX):
        raise ValueError(
            f"convention topic must start with {_CONVENTION_TOPIC_PREFIX!r} "
            f"(got {topic!r}); the prefix prevents collision with "
            "retro-try-<slug> adoption topics"
        )
    if not _KEBAB_SLUG_RE.match(topic):
        raise ValueError(
            f"convention topic must be kebab-case: {topic!r} does not match "
            f"{_KEBAB_SLUG_RE.pattern}"
        )


def _convention_topic_exists_filter(events: list[dict], topic: str) -> bool:
    """Pure filter: True if `events` contains a convention event with `topic`.
    Used to make force-drop convention emission idempotent — re-drops of
    the same Try MUST NOT append a duplicate convention.
    """
    for e in events:
        if e.get("type") == _common.CONVENTION and e.get("topic") == topic:
            return True
    return False


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


def run(
    action: str,
    smm_dir: Path,
    content: str,
    topic: str | None = None,
    event_id: str | None = None,
    force_adopt_topic: str | None = None,
    force_drop: bool = False,
    force_defer_until: str | None = None,
    convention_topic: str | None = None,
    convention_content: str | None = None,
) -> str:
    """Append the event and return its id.

    Retro Try actions: "adopt" | "defer" | "drop" (content-based — the
    `[refs: id1, id2]` suffix is consumed by event_builder.extract_refs_suffix
    inside _common.make_event).
    Triage actions: "triage-adopt" | "triage-defer" | "triage-drop"
    (event-id-based).

    The defer action enforces FORCE-CLOSE on Tries with 3+ prior deferrals;
    force_* params override. When defer + force_drop is paired with
    convention_topic + convention_content, a `convention` event is also
    appended. First-write-wins: a second invocation with the same topic
    skips the convention emission AND prints a stderr notice surfacing the
    discarded rationale — the drop event still fires.
    """
    _validate_convention_args(action, force_drop, convention_topic, convention_content)
    # agent_id is teammate-resolved attribution per the agent-id-semantics
    # ADR; the skill that produced the event lives in metadata or content.
    agent_id = identity.resolve_agent_id_from_cwd(os.getcwd())
    # Force-drop path may need events for cascade, prior-defer count, and
    # convention dedupe. Single locked read feeds all three filters; lazy
    # so adopt + triage paths skip the disk read entirely.
    events_cache: list[dict] | None = None

    def _events() -> list[dict]:
        nonlocal events_cache
        if events_cache is None:
            events_cache = _common.read_events_locked(smm_dir, _WATERMARK_ID)
        return events_cache

    match action:
        case "adopt":
            event = _common.make_event(
                "decision",
                agent_id,
                content,
                topic=topic,
            )
        case "defer":
            event = _build_defer_event(
                _events,
                agent_id,
                content,
                force_adopt_topic,
                force_drop,
                force_defer_until,
            )
        case "drop":
            event = _build_drop_event(_events, agent_id, content)
        case "triage-adopt" | "triage-defer" | "triage-drop":
            if event_id is None:
                raise ValueError(f"{action} requires --event-id")
            if not EVENT_ID_RE.match(event_id):
                raise ValueError(f"Invalid event ID format: {event_id}")
            _triage_dispositions = {
                "triage-adopt": DISPOSITION_ADOPTED,
                "triage-defer": DISPOSITION_DEFERRED,
                "triage-drop": DISPOSITION_DROPPED,
            }
            disposition = _triage_dispositions[action]
            metadata: dict = {METADATA_KEY_DISPOSITION: disposition}
            # Route the target id by evidence, mirroring extract_refs_suffix:
            # only a drop is terminal, so only a drop closes the target. Adopting
            # means taking the work ON — it links, and the target stays open
            # until the work lands. Deferring records neither: carrying an item
            # says nothing about it beyond "not now".
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
                (e for e in _events() if e.get("id") == event_id),
                None,
            )
            target_content = (target or {}).get("content", "")
            triage_content = (
                f"Triage: {disposition} {event_id[:8]} — {target_content}"
                if target_content
                else f"Triage: {disposition} {event_id[:8]}"
            )
            event = _common.make_event(
                "status",
                agent_id,
                triage_content,
                working_on=[],
                metadata=metadata,
                **link_field,
            )
        case _:
            raise ValueError(f"Unknown action: {action}")

    # Fit content to the event-type budget. Carried Try prose (often with its
    # rationale) can exceed the 200-char status budget; the `[refs: ...]`
    # suffix and any cascade hex IDs are already consumed into metadata by the
    # builders above, so truncating content here is lossless for linkage and
    # the FORCE-CLOSE gate. The canonical Try text lives in the retrospective.
    event["content"] = _common.truncate(
        event["content"], get_required_budget(event["type"])
    )

    errors = validate_event(event)
    if errors:
        raise ValueError(f"Event validation failed: {'; '.join(errors)}")
    _common.append_safe(smm_dir, event)
    if convention_topic and convention_content:
        # Reuses the same pre-append snapshot as the build_* path —
        # CONVENTION events aren't affected by the just-appended drop, so
        # the stale-by-one read is correctness-equivalent and saves a flock.
        if _convention_topic_exists_filter(_events(), convention_topic):
            # Honesty: surface the discard rather than silently dropping the
            # second rationale. Drop event still fired; only the duplicate
            # convention is skipped.
            print(
                f"Convention {convention_topic!r} already recorded; "
                "second rationale discarded.",
                file=sys.stderr,
            )
        else:
            conv_event = _common.make_event(
                _common.CONVENTION,
                agent_id,
                convention_content,
                topic=convention_topic,
            )
            # Fit to the convention budget, same as the main-event chokepoint —
            # an over-long rationale shouldn't fail the drop's convention record.
            conv_event["content"] = _common.truncate(
                conv_event["content"], get_required_budget(_common.CONVENTION)
            )
            conv_errors = validate_event(conv_event)
            if conv_errors:
                raise ValueError(
                    f"Convention event validation failed: {'; '.join(conv_errors)}"
                )
            _common.append_safe(smm_dir, conv_event)
    return event["id"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Adopt/defer/drop a retro Try item. The [refs: ...] suffix is "
            "auto-wired: a drop closes its target; an adopt or defer only "
            "references it."
        )
    )
    sub = parser.add_subparsers(dest="action", required=True)

    adopt = sub.add_parser("adopt", help="Record adoption as a decision event")
    adopt.add_argument("--smm-dir", type=Path, required=True)
    adopt.add_argument("--topic", required=True, help="Slugged retro-try-<slug>")
    adopt.add_argument("--content", required=True)

    defer = sub.add_parser("defer", help="Record deferral as a status event")
    defer.add_argument("--smm-dir", type=Path, required=True)
    defer.add_argument("--content", required=True)
    force_group = defer.add_mutually_exclusive_group()
    force_group.add_argument(
        "--force-adopt",
        metavar="TOPIC",
        help="Break FORCE-CLOSE gate by adopting with the given retro-try-<slug>",
    )
    force_group.add_argument(
        "--force-drop",
        action="store_true",
        help="Break FORCE-CLOSE gate by dropping the Try",
    )
    force_group.add_argument(
        "--force-defer-with-date",
        metavar="YYYY-MM-DD",
        help="Break FORCE-CLOSE gate by deferring with a target date",
    )
    defer.add_argument(
        "--record-convention-topic",
        metavar="SLUG",
        help=(
            "With --force-drop only: emit a convention event with this kebab-case "
            "topic (must start with 'retro-drop-') as a durable suppression record "
            "so future retros never re-propose this Try."
        ),
    )
    defer.add_argument(
        "--record-convention-content",
        metavar="TEXT",
        help=(
            "Rationale for the convention "
            "(required if --record-convention-topic is set)"
        ),
    )

    drop = sub.add_parser("drop", help="Record drop as a status event")
    drop.add_argument("--smm-dir", type=Path, required=True)
    drop.add_argument("--content", required=True)

    for name in ("triage-adopt", "triage-defer", "triage-drop"):
        p = sub.add_parser(name, help=f"Triage: {name.split('-')[1]}")
        p.add_argument("--smm-dir", type=Path, required=True)
        p.add_argument("--event-id", required=True, help="Event ID to triage")

    args = parser.parse_args()
    try:
        event_id = run(
            action=args.action,
            smm_dir=args.smm_dir,
            content=getattr(args, "content", ""),
            topic=getattr(args, "topic", None),
            event_id=getattr(args, "event_id", None),
            force_adopt_topic=getattr(args, "force_adopt", None),
            force_drop=getattr(args, "force_drop", False),
            force_defer_until=getattr(args, "force_defer_with_date", None),
            convention_topic=getattr(args, "record_convention_topic", None),
            convention_content=getattr(args, "record_convention_content", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(event_id)


if __name__ == "__main__":
    main()
