#!/usr/bin/env python3
"""Sprint retrospective detection for SessionStart.

Decides whether the incoming session should run a sprint retrospective
(because the previous session ended a sprint without retrospecting it)
instead of the regular session retrospective.

Scoped by sprint_id: the most recent sprint_end event is the candidate,
and we check whether a sprint_retro_done status event with the same
sprint_id exists after it. If the user started a NEW sprint without
retrospecting the old one, detection returns None — the session retro
will cover the events and the user has taken manual control.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from event_schema import (
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
    SPRINT_ACTION_END,
    SPRINT_ACTION_START,
    STATUS_ACTION_SPRINT_RETRO_DONE,
)


def _needs_sprint_retro(events: list[dict]) -> str | None:
    """Return the sprint_id that needs a retro, or None.

    A sprint retro is needed when:
    1. A sprint_end event exists (the most recent one).
    2. No sprint_retro_done status event has been recorded for that sprint_id.
    3. No newer sprint_start event exists (that would mean the user moved on
       without retro-ing the old sprint — session retro handles it).
    """
    # Walk backwards to find the most recent sprint_end.
    end_index = -1
    end_sprint_id: str | None = None
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if event.get("type") != EVENT_TYPE_SPRINT:
            continue
        metadata = event.get("metadata", {})
        if metadata.get("action") != SPRINT_ACTION_END:
            continue
        end_index = i
        end_sprint_id = metadata.get("sprint_id")
        break

    if end_sprint_id is None:
        return None

    # Scan events AFTER the sprint_end for either a matching retro_done or a
    # newer sprint_start (abandoned-sprint case).
    for event in events[end_index + 1 :]:
        event_type = event.get("type")
        metadata = event.get("metadata", {})
        action = metadata.get("action")

        if event_type == EVENT_TYPE_SPRINT and action == SPRINT_ACTION_START:
            # User abandoned the old sprint and started a new one.
            return None

        if (
            event_type == EVENT_TYPE_STATUS
            and action == STATUS_ACTION_SPRINT_RETRO_DONE
            and metadata.get("sprint_id") == end_sprint_id
        ):
            return None

    return end_sprint_id
