#!/usr/bin/env python3
"""Event-list helpers shared across hooks, smm engine, and tests."""

from collections.abc import Iterable


def events_of_type(events: Iterable[dict], type_name: str) -> list[dict]:
    """Return events whose `type` field equals `type_name`.

    Uses defensive `e.get("type")` so events missing the field are
    silently excluded (matches the prevailing call-site pattern).
    """
    return [e for e in events if e.get("type") == type_name]
