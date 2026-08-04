#!/usr/bin/env python3
"""How much of the event log a close's concern gate is allowed to see.

The merge gate exists to catch a close's unfixed findings, and for an ENCLOSING
close (sprint/plan/free) it could not see the ones that mattered most. The
sequence is sequential, not nested — `closing` is the sprint-singleton
in-pipeline lock, so a close inside a close cannot happen. What happens is:
story-closes run during the sprint and record concerns, each tagged with its own
cycle id; later an enclosing close mints a FRESH cycle id and a FRESH
CLOSE_START_TS; and those earlier concerns are dropped twice over, independently
— their tag differs from the gated cycle, AND their ts predates the enclosing
close's start. Fixing one filter alone changes no count, which is why the
previous, ancestry-shaped attempt shipped nothing.

So both filters read ONE window resolved here, and both are keyed off ONE
decision — the gated cycle's own `close_mode`. Two spellings of one rule is how
`smm_count` drifted before.

Why the mode is load-bearing rather than polish: all four close preloads `cat`
the same shared pipeline step, so they all emit the same `count-concerns` query.
Widening unconditionally would widen every STORY close too, and late in a sprint
almost every story close would then count its siblings' leftovers and lose its
auto-merge. A `story` close therefore keeps exactly today's behaviour: the
passed floor, and the shipped bare-inequality cross-cycle isolation.

Every fail-safe points the same way — COUNT. An unresolvable window, an
unresolvable mode, or a tag that joins to no `close_started` all leave the
concern in the count. Narrowing this gate is acceptable; widening the EXCLUSION
is the one move that is not, because the thing being excluded is the evidence
the gate exists to act on.

Nothing here imports `scripts/`, matching `close_cycle_tag` and
`concern_relevance`: `smm/` is the lower layer. `retro_metrics._event_in_sprint_window`
is the shipped "bound events by sprint start, fail open on None" primitive and
this PORTS its pattern rather than importing it, for that reason.
"""

import re
import sys
from pathlib import Path

import sprint_store
from event_categories import EVENT_TYPE_SPRINT
from event_metadata import (
    METADATA_KEY_CLOSE_CYCLE_ID,
    METADATA_KEY_CLOSE_MODE,
    STATUS_ACTION_CLOSE_STARTED,
    event_action,
)
from event_schema import SPRINT_ACTION_START

# The close modes that ENCLOSE story-closes, and so must see the whole sprint.
# `story` is deliberately absent — see the module docstring. Two other modules
# scope on this same trio for unrelated questions (which closes run a security
# review; which closes arm the Stop-gate marker), so the sets are not shared:
# adding a mode here is a statement about window width and nothing else.
WIDENING_CLOSE_MODES = frozenset({"sprint", "plan", "free"})

CLOSE_MODE_STORY = "story"


class ConcernWindow:
    """The floor and the tag rule for ONE `count-concerns` invocation.

    Built by `resolve`. Deliberately a value, not a set of free functions: the
    floor and the tag rule must come from the same mode decision, and handing
    the caller one object makes that structural instead of conventional.
    """

    def __init__(
        self,
        *,
        floor: str | None,
        cycle_id: str | None,
        widened: bool,
        close_starts: dict[str, dict],
        note: str | None,
    ) -> None:
        # The effective `--since-ts`, and — when `widened` — the sprint window
        # start the tag rule reads too. ONE field deliberately, because in the
        # widened case a separate `window_start` would always equal it: two
        # spellings of one bound is the exact drift this module exists to stop.
        # None means NO floor — never the passed since_ts, which is the
        # exclusion this module exists to lift.
        self.floor = floor
        self.cycle_id = cycle_id
        self.widened = widened
        self.close_starts = close_starts
        # A one-line degradation notice for stderr, or None when nothing was
        # dropped. Quiet by default: a note on every unscoped call would train
        # the operator to ignore the line that matters.
        self.note = note

    def excludes_tag(self, tag: str | None) -> bool:
        """Should a concern tagged `tag` be excluded from this count?

        Untagged never excludes (the untagged carve-outs in `smm_count` own that
        case), and the gated cycle's own tag never excludes.

        When this gate has NOT widened, a foreign tag excludes — the shipped
        rule, which exists to stop a CONCURRENT close's tagged concerns leaking
        into a sibling's count. That question is about simultaneity, not about
        the window, so it survives unchanged wherever the window did not widen.

        When it HAS widened, a foreign tag excludes only on positive proof that
        its close ran before this sprint: the tag joins to a `close_started`
        whose ts precedes the window floor. A tag that joins to nothing counts —
        4 of the 13 tagged cycle ids in this project's log have no
        `close_started` at all, because they predate the event. Unjoinable is
        unreadable evidence, never licence to exclude, the same rule
        `concern_relevance._names_existing_code` applies to a path that does not
        exist.
        """
        if not self.cycle_id or tag is None or tag == self.cycle_id:
            return False
        if not self.widened:
            return True
        if self.floor is None:
            return False
        started = self.close_starts.get(tag)
        if started is None:
            return False
        ts = started.get("ts")
        if not isinstance(ts, str) or not ts:
            return False
        return ts < self.floor


def close_started_index(events: list[dict]) -> dict[str, dict]:
    """Map each close-cycle id to the `close_started` event that opened it.

    Latest wins, by log position rather than timestamp — the same ordering
    `close_cycle_stop_gate.reviewer_completed_this_cycle` uses to find its
    anchoring close_started, and no timestamp math to get wrong.
    """
    index: dict[str, dict] = {}
    for event in events:
        if event_action(event) != STATUS_ACTION_CLOSE_STARTED:
            continue
        cycle_id = (event.get("metadata") or {}).get(METADATA_KEY_CLOSE_CYCLE_ID)
        if isinstance(cycle_id, str) and cycle_id:
            index[cycle_id] = event
    return index


_ISO_DATE_PREFIX_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _lexical_floor(value: object) -> str | None:
    """*value* as a floor safe to compare byte-wise, or None when it is not one.

    A floor is compared lexicographically against full ISO event timestamps, so
    a string that is not at least a `YYYY-MM-DD` prefix is not a weak floor but
    an INVERTED one: "TBD" sorts ABOVE every real ts, so trusting it excludes
    the entire log — silently widening the exclusion, the one direction this
    module forbids. sprint.json's `started` is required by the schema but its
    SHAPE is unvalidated and `xp-sprint-start` SKILL.md has an LLM author it, so
    it is checked here rather than trusted. None then reaches the same
    no-floor-and-say-so path as a missing sprint.
    """
    if not isinstance(value, str) or not _ISO_DATE_PREFIX_RE.match(value):
        return None
    return value


def sprint_window_start(events: list[dict], smm_dir: Path) -> str | None:
    """The current sprint's start bound, or None when it cannot be resolved.

    Prefers the `type=sprint`, `metadata.action=start` event already in the
    events the caller is iterating: it carries a full ISO ts (finer than
    sprint.json's date-only `started`) and costs no extra file read. Falls back
    to sprint.json, which is a valid lexicographic floor against a full ISO ts
    even at date granularity — "2026-07-31T09:00:00+00:00" >= "2026-07-20".

    Either leg must pass `_lexical_floor` to be used. Skipping a malformed
    sprint-start event only ever reaches an EARLIER one, so every degradation
    here widens the window rather than the exclusion.

    `load_sprint_fail_open` because this read is advisory: a corrupt sprint.json
    must degrade the gate loudly, not crash a close mid-pipeline. Same posture
    as `trailer_gate._started_from`, the other close-path caller.
    """
    for event in reversed(events):
        if event.get("type") != EVENT_TYPE_SPRINT:
            continue
        if event_action(event) != SPRINT_ACTION_START:
            continue
        floor = _lexical_floor(event.get("ts"))
        if floor:
            return floor
    sprint = sprint_store.load_sprint_fail_open(smm_dir)
    return _lexical_floor(sprint.get("started") if isinstance(sprint, dict) else None)


def _close_mode(started: dict | None) -> str | None:
    """The gated close's mode, or None when it cannot be read.

    A blank or non-string mode reads as unknown rather than as a mode, matching
    `close_cycle_stop_gate._anchors_this_gate`'s treatment of the same field.
    Unknown fails closed here too, just in the other direction: that gate widens
    its anchor search, this one widens its window.
    """
    if started is None:
        return None
    raw = (started.get("metadata") or {}).get(METADATA_KEY_CLOSE_MODE)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def resolve(
    events: list[dict],
    smm_dir: Path,
    *,
    cycle_id: str | None,
    since_ts: str | None,
) -> ConcernWindow:
    """Decide how wide this close's concern gate looks.

    Three outcomes, chosen by the gated cycle's `close_mode`:

    - `story` → the passed `since_ts`, unchanged, and the shipped tag rule.
    - `sprint`/`plan`/`free` → the sprint's start, and a tag rule that excludes
      only a close provably from an earlier sprint. When the sprint window
      cannot be resolved: NO floor and no tag exclusion at all.
    - mode unreadable (no `--cycle-id`, no `close_started` for it, blank mode) →
      NO floor, and the shipped tag rule. The widest window, because a cycle we
      cannot identify gives us no window to trust.
    """
    close_starts = close_started_index(events)
    started = close_starts.get(cycle_id) if cycle_id else None
    mode = _close_mode(started)

    if mode == CLOSE_MODE_STORY:
        return ConcernWindow(
            floor=since_ts,
            cycle_id=cycle_id,
            widened=False,
            close_starts=close_starts,
            note=None,
        )

    if mode in WIDENING_CLOSE_MODES:
        window_start = sprint_window_start(events, smm_dir)
        note = None
        if window_start is None:
            note = (
                f"close mode {mode!r} needs the sprint window, and neither a "
                "sprint start event nor sprint.json yields one; counting with "
                "NO time floor and excluding no close-cycle tag (fail closed)"
            )
        return ConcernWindow(
            floor=window_start,
            cycle_id=cycle_id,
            widened=True,
            close_starts=close_starts,
            note=note,
        )

    note = None
    if since_ts:
        why = (
            f"cycle {cycle_id} has no close_started event, so its close mode is unknown"
            if cycle_id
            else "no --cycle-id was given, so no close mode can be read"
        )
        note = (
            f"{why}; ignoring --since-ts {since_ts} and counting with NO time "
            "floor (fail closed — a floor we cannot justify is how an "
            "enclosing close came to miss the findings it exists to catch)"
        )
    return ConcernWindow(
        floor=None,
        cycle_id=cycle_id,
        widened=False,
        close_starts=close_starts,
        note=note,
    )


def report(window: ConcernWindow, subcommand: str) -> None:
    """Print `window`'s degradation notice, if any, to stderr.

    stderr, never stdout: these count subcommands are captured with `$(...)` by
    the close pipeline's auto-merge gate, so a stray stdout line becomes the
    count.
    """
    if window.note:
        print(f"{subcommand}: {window.note}", file=sys.stderr)
