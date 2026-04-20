#!/usr/bin/env python3
"""Duplicate-debt probe: Jaccard similarity on normalized word sets.

Core functions (probe_duplicate_debt, build_advisory_concern) are pure.
run_probe_and_append is the wiring entry point called by append_safe,
bulk_append_safe, and _append_impl.main after a successful debt write.
"""

import contextlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from event_builder import generate_id

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> set[str]:
    """Normalize text to a set of meaningful lowercase words."""
    text = _PUNCT_RE.sub(" ", text.lower())
    return {w for w in text.split() if w and w not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two word sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def probe_duplicate_debt(
    smm_dir: Path,
    content: str,
    window: int = 20,
    threshold: float = 0.8,
    exclude_id: str = "",
) -> list[dict]:
    """Check recent debt events for near-duplicates of content.

    Returns a list of {debt_id, similarity} dicts for debts above threshold.
    Pure function: reads events.jsonl but never writes.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return []

    raw = events_file.read_text(encoding="utf-8")
    if not raw.strip():
        return []

    debts: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") != "debt":
            continue
        if event.get("metadata", {}).get("resolved"):
            continue
        if exclude_id and event.get("id") == exclude_id:
            continue
        debts.append(event)

    recent = debts[-window:]
    new_words = _normalize(content)
    if not new_words:
        return []

    matches: list[dict] = []
    for debt in recent:
        old_words = _normalize(debt.get("content", ""))
        sim = _jaccard(new_words, old_words)
        if sim > threshold:
            matches.append({"debt_id": debt.get("id", ""), "similarity": sim})

    return matches


def build_advisory_concern(
    matches: list[dict], new_debt_id: str, agent_id: str
) -> dict:
    """Build an advisory concern event for duplicate debt matches."""
    best = max(matches, key=lambda m: m["similarity"])
    return {
        "id": generate_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "concern",
        "severity": "low",
        "agent_id": agent_id,
        "content": (
            f"Possible duplicate debt: new debt {new_debt_id} "
            f"is {best['similarity']:.0%} similar to existing debt {best['debt_id']}"
        ),
        "schema_version": 1,
        "metadata": {"duplicate_of": best["debt_id"]},
    }


def run_probe_and_append(smm_dir: Path, event: dict) -> None:
    """If event is debt, check for near-duplicates and append advisory.

    Safe to call for any event type — returns immediately for non-debt.
    Swallows all errors: advisory is best-effort, never blocks the write.
    """
    try:
        if event.get("type") != "debt":
            return
        matches = probe_duplicate_debt(
            smm_dir, event.get("content", ""), exclude_id=event.get("id", "")
        )
        if matches:
            advisory = build_advisory_concern(
                matches, event.get("id", ""), event.get("agent_id", "unknown")
            )
            import _append_impl

            with contextlib.suppress(_append_impl.LockTimeoutError):
                _append_impl.append_event(smm_dir, advisory)
    except Exception:
        pass
