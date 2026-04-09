#!/usr/bin/env python3
"""Schema constants and validator for shared_mental_model.json.

Single source of truth for what constitutes a valid curated SMM document.
No I/O, no file operations — pure validation logic and shared constants.

Mirrors the `event_schema.py` pattern: hand-rolled validator, no external
`jsonschema` dependency, stdlib-only.
"""

import re
from dataclasses import dataclass
from datetime import datetime

PILLAR_INTENT = "intent"
PILLAR_CONSTRAINTS = "constraints"
PILLAR_RISKS = "risks"
PILLAR_WISDOM = "wisdom"

PILLARS = (PILLAR_INTENT, PILLAR_CONSTRAINTS, PILLAR_RISKS, PILLAR_WISDOM)

SOURCE_SEED = "seed"
SOURCE_EVENT = "event"
SOURCE_CURATED = "curated"

VALID_SOURCES = frozenset({SOURCE_SEED, SOURCE_EVENT, SOURCE_CURATED})

VALID_INTENT_TYPES = frozenset({"goal", "customer_intent"})
VALID_CONSTRAINT_TYPES = frozenset({"decision", "convention"})
VALID_RISK_TYPES = frozenset({"concern", "assumption", "debt", "question"})
VALID_RISK_SEVERITIES = frozenset({"problem", "uncertainty", "debt"})

# UUID v4 regex — copied verbatim from schema.json:10 for consistency.
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _is_uuid4(value: object) -> bool:
    return isinstance(value, str) and bool(_UUID4_RE.match(value))


def _is_iso8601(value: object) -> bool:
    if not isinstance(value, str):
        return False
    # datetime.fromisoformat parses the canonical offset form we write
    # (e.g. "2026-04-09T02:15:28+00:00") on Python 3.10+; bare "Z" suffix
    # is rejected here by design — we only emit offset-form timestamps.
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def empty_smm() -> dict:
    """Return a canonical empty SMM document."""
    return {
        PILLAR_INTENT: [],
        PILLAR_CONSTRAINTS: [],
        PILLAR_RISKS: [],
        PILLAR_WISDOM: [],
    }


@dataclass(frozen=True)
class PillarSpec:
    """Pillar-specific validation rules.

    `valid_types` may be empty (wisdom) — empty means the `type` field
    is not validated against an enum even when present.
    """

    name: str
    valid_types: frozenset
    extra_string_fields: tuple[str, ...] = ()
    severity_enum: frozenset | None = None


_PILLAR_SPECS: tuple[PillarSpec, ...] = (
    PillarSpec(PILLAR_INTENT, VALID_INTENT_TYPES),
    PillarSpec(
        PILLAR_CONSTRAINTS,
        VALID_CONSTRAINT_TYPES,
        extra_string_fields=("topic",),
    ),
    PillarSpec(
        PILLAR_RISKS,
        VALID_RISK_TYPES,
        severity_enum=VALID_RISK_SEVERITIES,
    ),
    PillarSpec(PILLAR_WISDOM, frozenset()),
)


def _validate_base_entry(entry: object, pillar: str, idx: int) -> list[str]:
    """Validate the common id/content/source/ts fields on every entry."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"{pillar}[{idx}] must be an object"]

    for field_name in ("id", "content", "source", "ts"):
        if field_name not in entry:
            errors.append(f"{pillar}[{idx}] missing required field: {field_name}")
    if errors:
        return errors

    if not _is_uuid4(entry["id"]):
        errors.append(f"{pillar}[{idx}] field 'id' must be a UUID v4 string")

    if not isinstance(entry["content"], str) or not entry["content"]:
        errors.append(f"{pillar}[{idx}] field 'content' must be a non-empty string")

    if entry["source"] not in VALID_SOURCES:
        errors.append(
            f"{pillar}[{idx}] field 'source' must be one of {sorted(VALID_SOURCES)}"
        )

    if not _is_iso8601(entry["ts"]):
        errors.append(f"{pillar}[{idx}] field 'ts' must be an ISO-8601 timestamp")

    if "source_event_id" in entry and not _is_uuid4(entry["source_event_id"]):
        errors.append(
            f"{pillar}[{idx}] field 'source_event_id' must be a UUID v4 string"
        )

    return errors


def _validate_pillar(entries: object, spec: PillarSpec) -> list[str]:
    """Validate entries in one pillar — base fields + pillar-specific rules."""
    errors: list[str] = []
    if not isinstance(entries, list):
        return [f"Pillar {spec.name!r} must be an array"]

    for idx, entry in enumerate(entries):
        base_errors = _validate_base_entry(entry, spec.name, idx)
        errors.extend(base_errors)
        if base_errors:
            continue  # Skip pillar-specific checks — the base is already broken.

        if "type" in entry:
            if not isinstance(entry["type"], str):
                errors.append(f"{spec.name}[{idx}] field 'type' must be a string")
            elif spec.valid_types and entry["type"] not in spec.valid_types:
                errors.append(
                    f"{spec.name}[{idx}] field 'type' must be one of "
                    f"{sorted(spec.valid_types)}"
                )

        for extra in spec.extra_string_fields:
            if extra in entry and not isinstance(entry[extra], str):
                errors.append(f"{spec.name}[{idx}] field {extra!r} must be a string")

        if spec.severity_enum is not None and "severity" in entry:
            if not isinstance(entry["severity"], str):
                errors.append(f"{spec.name}[{idx}] field 'severity' must be a string")
            elif entry["severity"] not in spec.severity_enum:
                errors.append(
                    f"{spec.name}[{idx}] field 'severity' must be one of "
                    f"{sorted(spec.severity_enum)}"
                )

    return errors


def _collect_all_ids(data: dict) -> list[tuple[str, int, str]]:
    """Return a flat list of (pillar, idx, id) tuples across all pillars."""
    ids: list[tuple[str, int, str]] = []
    for pillar in PILLARS:
        entries = data.get(pillar, [])
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                ids.append((pillar, idx, entry["id"]))
    return ids


def validate_smm(data: object) -> list[str]:
    """Validate a curated SMM document.

    Returns a list of error strings — empty list means valid.
    Mirrors `event_schema.validate_event()` contract.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["SMM document must be an object"]

    for pillar in PILLARS:
        if pillar not in data:
            errors.append(f"Missing required pillar: {pillar}")
    if errors:
        return errors

    for spec in _PILLAR_SPECS:
        errors.extend(_validate_pillar(data[spec.name], spec))

    # Cross-pillar id uniqueness
    seen: dict[str, tuple[str, int]] = {}
    for pillar, idx, id_ in _collect_all_ids(data):
        if id_ in seen:
            prev_pillar, prev_idx = seen[id_]
            errors.append(
                f"Duplicate id {id_!r}: {prev_pillar}[{prev_idx}] and "
                f"{pillar}[{idx}] — ids must be unique across all pillars"
            )
        else:
            seen[id_] = (pillar, idx)

    return errors
