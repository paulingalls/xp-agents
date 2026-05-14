#!/usr/bin/env python3
"""Persistent ring-buffer for session_history.json.

session_history.json sits beside events.jsonl in SMM_DIR and holds the
last N session summaries plus their carry_forward items. Schema is
versioned so future migrations can introspect the on-disk shape:

    {
      "version": 1,
      "entries": [
        {
          "ts": ISO-8601 string,
          "summary": str,
          "carry_forward": [
            {"note": str, "references": [event_id, ...], "recommendation": str},
            ...
          ]
        },
        ...
      ]
    }

I/O follows the smm_store / system_context_store template: atomic write
via tempfile + rename, symlink rejection, fail-loud on corrupt JSON or
schema-invalid content. Pure module — no CLI; story-003's write_history.py
is the CLI front-end.
"""

import json
from pathlib import Path

from _append_impl import write_text_atomic
from append_validation import parse_jsonl
from event_schema import EVENT_TYPE_SESSION_END, sessions_since_event
from resolution import collect_all_resolved_ids

SESSION_HISTORY_FILENAME = "session_history.json"
SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 5

# Number of recent entries to surface to retro and housekeeper agent
# inputs. Mirrors the kickoff LAST_SESSION render limit so all consumers
# see the same window.
RECENT_SUMMARIES_LIMIT = 2

# Staleness status vocabulary — single source of truth for callers
# (CLI, retro/housekeeper input builders, kickoff preload).
STALENESS_FRESH = "fresh"
STALENESS_STALE = "stale"
STALENESS_UNKNOWN = "unknown"


def validate_session_history(data: object) -> list[str]:
    """Validate a session history document.

    Returns a list of error strings — empty list means valid. Mirrors
    ``smm_schema.validate_smm`` contract.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["session_history must be an object"]

    if data.get("version") != SCHEMA_VERSION:
        errors.append(
            f"session_history version must be {SCHEMA_VERSION}, "
            f"got {data.get('version')!r}"
        )

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("session_history.entries must be an array")
        return errors

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{idx}] must be an object")
            continue
        if not isinstance(entry.get("ts"), str):
            errors.append(f"entries[{idx}].ts must be a string")
        if not isinstance(entry.get("summary"), str):
            errors.append(f"entries[{idx}].summary must be a string")
        cf = entry.get("carry_forward")
        if not isinstance(cf, list):
            errors.append(f"entries[{idx}].carry_forward must be an array")
            continue
        for cf_idx, item in enumerate(cf):
            if not isinstance(item, dict):
                errors.append(
                    f"entries[{idx}].carry_forward[{cf_idx}] must be an object"
                )
                continue
            # `references` is the one field prune_resolved relies on; pin
            # its shape so corrupt data fails loud at save/load time
            # rather than silently surviving the prune cascade.
            refs = item.get("references")
            if refs is not None and not (
                isinstance(refs, list) and all(isinstance(r, str) for r in refs)
            ):
                errors.append(
                    f"entries[{idx}].carry_forward[{cf_idx}].references "
                    "must be a list of strings"
                )

    return errors


def empty_history() -> dict:
    """Return a fresh, valid session_history document."""
    return {"version": SCHEMA_VERSION, "entries": []}


def load_history(smm_dir: Path) -> dict:
    """Read session_history.json from disk.

    Returns:
        Parsed dict on success, or ``empty_history()`` if the file does
        not exist (fresh install / first session).

    Raises:
        ValueError: If the file exists but contains malformed JSON or
            fails schema validation.
        OSError: If the path is a symlink.
    """
    path = smm_dir / SESSION_HISTORY_FILENAME
    if path.is_symlink():
        raise OSError(f"session_history path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_history()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt session_history at {path}: {exc}") from exc

    errors = validate_session_history(data)
    if errors:
        raise ValueError(
            f"Schema-invalid session_history at {path}: {'; '.join(errors)}"
        )
    return data


def save_history(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write session_history.json.

    Raises:
        ValueError: If the data fails schema validation. The existing
            file on disk is left untouched.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SESSION_HISTORY_FILENAME
    if path.is_symlink():
        raise OSError(f"session_history path is a symlink: {path}")

    errors = validate_session_history(data)
    if errors:
        raise ValueError(f"session_history validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))


def append_entry(
    smm_dir: Path, entry: dict, *, max_entries: int = DEFAULT_MAX_ENTRIES
) -> None:
    """Append a single entry, evicting oldest entries beyond ``max_entries``.

    Newest entry is appended at the end; eviction trims the head so the
    surviving slice is the most-recent ``max_entries`` in chronological
    order. Caller is responsible for entry validity — save_history will
    reject malformed shapes loudly.
    """
    data = load_history(smm_dir)
    data["entries"].append(entry)
    if len(data["entries"]) > max_entries:
        data["entries"] = data["entries"][-max_entries:]
    save_history(smm_dir, data)


def filter_session_end_timestamps(events: list[dict]) -> list[str]:
    """Return ascending list of ``session_end`` event timestamps from *events*.

    In-memory filter+sort; callers that already have events loaded
    (retro, materialize) use this directly to avoid re-reading
    events.jsonl. Disk-read callers use ``read_session_end_timestamps``
    which delegates here.
    """
    timestamps = [
        ts
        for e in events
        if e.get("type") == EVENT_TYPE_SESSION_END and (ts := e.get("ts", ""))
    ]
    timestamps.sort()
    return timestamps


def read_session_end_timestamps(smm_dir: Path) -> list[str]:
    """Return ascending list of ``session_end`` event timestamps from disk.

    Returns ``[]`` when ``events.jsonl`` is absent or unreadable so the
    staleness scan stays resilient when consumers run before init.
    Reuses ``append_validation.parse_jsonl`` for tolerant parsing —
    same path used by ``compact.py`` and other reader code.
    """
    path = smm_dir / "events.jsonl"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    events, _ = parse_jsonl(raw)
    return filter_session_end_timestamps(events)


def compute_staleness(entry: dict, session_end_timestamps: list[str]) -> dict:
    """Classify *entry* freshness against the sorted *session_end_timestamps*.

    Mechanics: ``/xp-end-session`` writes the summary at ``T1`` and the
    SessionEnd hook later fires the entry's own session_end event at
    ``T2 > T1``. So in normal flow exactly one session_end is newer than
    the entry — that's the fresh case. Each additional newer session_end
    represents a subsequent session that ended without a summary.

    Returns ``{"status": <fresh|stale|unknown>, "skipped_sessions": int}``.

    * ``count == 0``: ``unknown`` — entry is from the current still-running
      session, OR older session_ends were archived past retention.
    * ``count == 1``: ``fresh`` — only the entry's own session_end is newer.
    * ``count >= 2``: ``stale`` with ``skipped_sessions = count - 1``.
    """
    count = sessions_since_event(session_end_timestamps, entry.get("ts", ""))
    if count == 0:
        return {"status": STALENESS_UNKNOWN, "skipped_sessions": 0}
    if count == 1:
        return {"status": STALENESS_FRESH, "skipped_sessions": 0}
    return {"status": STALENESS_STALE, "skipped_sessions": count - 1}


def render_markdown(
    entries: list[dict],
    *,
    session_end_timestamps: list[str] | None = None,
) -> str:
    """Render *entries* as a ``### LAST_SESSION`` markdown block.

    Mirrors the original render_history.py format: ONE ``### LAST_SESSION``
    header followed by each entry's summary and ``carry_forward`` notes.
    Event ids in ``references`` are NEVER rendered — humans don't read them.

    When *session_end_timestamps* is provided AND the most-recent entry's
    staleness is ``stale``, the header is annotated with ``(stale — N
    sessions ended without /xp-end-session since this summary)``. The
    annotation reflects the most-recent entry because older entries are
    obviously older — the block as a whole is "stale" when the latest is.

    Returns ``""`` when *entries* is empty so the kickoff preload can
    skip the section cleanly on first-session installs.
    """
    if not entries:
        return ""

    header = "### LAST_SESSION"
    if session_end_timestamps is not None:
        status = compute_staleness(entries[-1], session_end_timestamps)
        if status["status"] == STALENESS_STALE:
            n = status["skipped_sessions"]
            header += (
                f" (stale — {n} session{'s' if n != 1 else ''} ended without "
                f"/xp-end-session since this summary)"
            )

    lines: list[str] = [header, ""]
    for entry in entries:
        if summary := entry.get("summary", ""):
            lines.append(summary)
        for item in entry.get("carry_forward", []):
            if note := item.get("note", ""):
                lines.append(f"- {note}")
            if rec := item.get("recommendation", ""):
                lines.append(f"  → {rec}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def gather_recent_summaries(
    smm_dir: Path,
    *,
    session_end_timestamps: list[str] | None = None,
    limit: int = RECENT_SUMMARIES_LIMIT,
) -> list[dict]:
    """Load the last *limit* session_history entries with staleness annotated.

    Used by both ``retrospective.py`` and ``materialize.py`` to surface
    cross-session narrative context to the retro and housekeeper agents.
    Fail-quiet on missing / corrupt history — recent_summaries is a hint,
    not a load-bearing input.

    When *session_end_timestamps* is provided (the materialize path,
    which already scans events for aging), it's used directly. Otherwise
    the helper falls back to ``read_session_end_timestamps`` — caller
    convenience for paths that don't already have the timestamps in hand.
    """
    try:
        data = load_history(smm_dir)
    except (ValueError, OSError):
        return []
    entries = data.get("entries", [])
    if not entries:
        return []
    ses = (
        session_end_timestamps
        if session_end_timestamps is not None
        else read_session_end_timestamps(smm_dir)
    )
    annotated: list[dict] = []
    for entry in entries[-limit:]:
        item = dict(entry)
        item["staleness"] = compute_staleness(entry, ses)
        annotated.append(item)
    return annotated


def prune_resolved(smm_dir: Path, resolutions: dict) -> int:
    """Drop carry_forward items whose every reference is now resolved.

    Walks each entry's carry_forward; an item is dropped iff it has at
    least one reference AND every reference id appears in
    ``resolution.collect_all_resolved_ids(resolutions)``. Items with no
    references are kept (no resolution claim possible). Saves only when
    at least one item was dropped.

    Returns the number of carry_forward items pruned.
    """
    resolved_ids = collect_all_resolved_ids(resolutions)
    if not resolved_ids:
        return 0

    data = load_history(smm_dir)
    pruned_count = 0
    for entry in data["entries"]:
        original = entry.get("carry_forward", [])
        kept: list[dict] = []
        for item in original:
            refs = item.get("references", [])
            if refs and all(ref in resolved_ids for ref in refs):
                pruned_count += 1
                continue
            kept.append(item)
        entry["carry_forward"] = kept

    if pruned_count:
        save_history(smm_dir, data)
    return pruned_count
