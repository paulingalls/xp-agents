#!/usr/bin/env python3
"""Load/save for shared_mental_model.json.

The curated SMM is the persistent store for pillar content. This module
owns all I/O for that file: atomic writes, schema validation on save,
fail-loud on corrupt reads, symlink rejection.

Counterpart to smm_schema.py (pure validation) and smm_cli.py (rendering
and CLI). This module is stateful — it touches the filesystem.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import materialize
from _append_impl import write_text_atomic
from resolution import resolve_prefix
from smm_schema import PILLARS, empty_smm, validate_entry, validate_smm

SMM_FILENAME = "shared_mental_model.json"


def load_smm(smm_dir: Path) -> dict:
    """Read the curated SMM from disk.

    Returns:
        Parsed SMM dict on success, or ``empty_smm()`` if the file
        does not exist (fresh install).

    Raises:
        ValueError: If the file exists but contains malformed JSON or
            fails schema validation. This is deliberate — silently
            returning empty on corruption would re-create the seed-wipe
            bug this module was built to fix.
        OSError: If the path is a symlink.
    """
    path = smm_dir / SMM_FILENAME
    if path.is_symlink():
        raise OSError(f"SMM path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_smm()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt SMM file at {path}: {exc}") from exc

    errors = validate_smm(data)
    if errors:
        raise ValueError(f"Schema-invalid SMM file at {path}: {'; '.join(errors)}")

    return data


def save_smm(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write the curated SMM.

    Raises:
        ValueError: If the data fails schema validation. The existing
            file on disk is left untouched.
        OSError: If the target path is a symlink.
    """
    path = smm_dir / SMM_FILENAME
    if path.is_symlink():
        raise OSError(f"SMM path is a symlink: {path}")

    errors = validate_smm(data)
    if errors:
        raise ValueError(f"SMM validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))


def add_item(
    smm_dir: Path,
    pillar: str,
    content: str,
    *,
    type: str | None = None,
    topic: str | None = None,
    severity: str | None = None,
    source: str = "curated",
    source_event_id: str | None = None,
) -> str:
    """Add a new entry to a pillar. Returns the generated UUID."""
    if pillar not in PILLARS:
        raise ValueError(f"Unknown pillar: {pillar!r}")

    item_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    entry: dict = {"id": item_id, "content": content, "source": source, "ts": ts}
    if type is not None:
        entry["type"] = type
    if topic is not None:
        entry["topic"] = topic
    if severity is not None:
        entry["severity"] = severity
    if source_event_id is not None:
        entry["source_event_id"] = source_event_id

    errors = validate_entry(entry, pillar)
    if errors:
        raise ValueError(f"Invalid entry: {'; '.join(errors)}")

    smm = load_smm(smm_dir)
    smm[pillar].append(entry)
    save_smm(smm_dir, smm)
    return item_id


def _find_item(smm: dict, item_id: str) -> tuple[str, int, dict]:
    """Find entry by ID across all pillars. Returns (pillar, index, entry)."""
    for pillar in PILLARS:
        for idx, entry in enumerate(smm.get(pillar, [])):
            if entry.get("id") == item_id:
                return pillar, idx, entry
    raise ValueError(f"No item with id {item_id!r}")


def update_item(
    smm_dir: Path,
    item_id: str,
    *,
    content: str | None = None,
    type: str | None = None,
    topic: str | None = None,
    severity: str | None = None,
) -> None:
    """Patch fields on an existing entry. Preserves id, source, ts."""
    smm = load_smm(smm_dir)
    pillar, idx, entry = _find_item(smm, item_id)

    if content is not None:
        entry["content"] = content
    if type is not None:
        entry["type"] = type
    if topic is not None:
        entry["topic"] = topic
    if severity is not None:
        entry["severity"] = severity

    errors = validate_entry(entry, pillar)
    if errors:
        raise ValueError(f"Invalid after patch: {'; '.join(errors)}")

    smm[pillar][idx] = entry
    save_smm(smm_dir, smm)


def remove_item(smm_dir: Path, item_id: str) -> None:
    """Remove an entry by ID. Raises ValueError if not found."""
    smm = load_smm(smm_dir)
    pillar, idx, _ = _find_item(smm, item_id)
    del smm[pillar][idx]
    save_smm(smm_dir, smm)


EVENT_TYPE_TO_PILLAR: dict[str, str] = {
    "goal": "intent",
    "customer_input": "intent",
    "customer_intent": "intent",
    "decision": "constraints",
    "convention": "constraints",
    "concern": "risks",
    "assumption": "risks",
    "debt": "risks",
    "question": "risks",
    "discovery": "wisdom",
    "retrospective": "wisdom",
}

_EVENT_TYPE_TO_ENTRY_TYPE: dict[str, str] = {
    "goal": "goal",
    "customer_input": "customer_intent",
    "customer_intent": "customer_intent",
    "decision": "decision",
    "convention": "convention",
    "concern": "concern",
    "assumption": "assumption",
    "debt": "debt",
    "question": "question",
}


def promote_event(
    smm_dir: Path,
    event_id: str,
    pillar: str | None = None,
) -> str:
    """Promote an event to a curated SMM entry. Returns new UUID."""
    events, _ = materialize.parse_events(smm_dir)
    by_id = {e["id"]: e for e in events}

    result = resolve_prefix(event_id, by_id)
    if result is None:
        matches = [k for k in by_id if k.startswith(event_id)]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous prefix {event_id!r}: matches {len(matches)} events"
            )
        raise ValueError(f"Event not found: {event_id!r}")

    full_id, event = result
    event_type = event["type"]

    target_pillar = pillar or EVENT_TYPE_TO_PILLAR.get(event_type)
    if target_pillar is None:
        raise ValueError(
            f"Cannot promote event type {event_type!r} — no default pillar mapping"
        )

    entry_type = _EVENT_TYPE_TO_ENTRY_TYPE.get(event_type)

    kwargs: dict = {}
    if entry_type is not None:
        kwargs["type"] = entry_type
    if "topic" in event:
        kwargs["topic"] = event["topic"]
    if "severity" in event:
        kwargs["severity"] = event["severity"]

    return add_item(
        smm_dir,
        target_pillar,
        event["content"],
        source="event",
        source_event_id=full_id,
        **kwargs,
    )
