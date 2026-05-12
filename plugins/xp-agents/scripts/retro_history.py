#!/usr/bin/env python3
"""Retrospective history gathering and Try-item annotation.

Reads the last N retrospective JSON files from ${SMM_DIR}/retrospectives/
and slims them for the retro analyst agent. Also cross-references the
most recent retro's Try items against this session's resolution map so
items that were already honored don't get re-flagged as "not honored".
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
from event_schema import DISPOSITION_ADOPTED, DISPOSITION_DROPPED

MAX_RETRO_HISTORY = 1
MAX_RETRO_FILE_SIZE = 1_048_576  # 1 MB

# 12+ char hex token — matches event IDs in Try text.
# Dict lookup downstream filters false positives (commit SHAs etc).
HEX_ID_RE = re.compile(r"\b[0-9a-f]{12,}\b")


def _slim_try_item(item) -> dict:
    """Slim a try item to {id?, content, event_refs}, handling legacy strings."""
    if isinstance(item, dict):
        slim: dict = {
            "content": item.get("content", ""),
            "event_refs": item.get("event_refs", []),
        }
        own_id = item.get("id")
        if own_id:
            slim["id"] = own_id
        return slim
    return {"content": item, "event_refs": []}


def gather_retro_history(smm_dir: Path, limit: int = MAX_RETRO_HISTORY) -> list[dict]:
    """Read the last N retrospective JSON files, slimmed for the retro agent.

    `keep` and `fix` become content-only strings. `try` becomes a list of
    `{content, event_refs}` dicts so the annotate step can cross-reference
    event IDs against the current session's resolutions. `analysis_notes`
    is preserved when present (carries cross-session trends). Legacy retros
    with list-of-strings `try` are migrated to the new shape on read.
    """
    retro_dir = smm_dir / marker_names.RETROSPECTIVES_DIR
    if not retro_dir.is_dir():
        return []

    files = sorted(retro_dir.glob("*.json"), reverse=True)
    result: list[dict] = []
    for f in files[:limit]:
        try:
            if f.stat().st_size > MAX_RETRO_FILE_SIZE:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                slimmed: dict = {}
                if "timestamp" in data:
                    slimmed["timestamp"] = data["timestamp"]
                for field in ("keep", "fix"):
                    items = data.get(field, [])
                    slimmed[field] = [
                        item.get("content", item) if isinstance(item, dict) else item
                        for item in items
                    ]
                slimmed["try"] = [_slim_try_item(it) for it in data.get("try", [])]
                if "analysis_notes" in data:
                    slimmed["analysis_notes"] = data["analysis_notes"]
                result.append(slimmed)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def annotate_try_status(previous_retros: list[dict], resolutions_map: dict) -> None:
    """Annotate and filter Try items on previous_retros[0].

    Attaches a parallel try_status list, then strips dropped Tries from
    both try and try_status so the retro analyst never sees them.

    Only the most recent retro gets annotated — older retros already
    went through a retro cycle, so their Try items are not candidates
    for re-proposal. For each Try item, collect candidate ids: 12+ char
    hex tokens in content, the event_refs list, and the Try's own id.
    Direct lookup against resolutions_map (which keys on full event ids).
    """
    if not previous_retros:
        return
    latest = previous_retros[0]
    statuses: list[dict] = []
    for item in latest.get("try", []):
        content = item.get("content", "") if isinstance(item, dict) else item
        refs = item.get("event_refs", []) if isinstance(item, dict) else []
        own_id = item.get("id", "") if isinstance(item, dict) else ""
        tokens = set(HEX_ID_RE.findall(content)) | set(refs)
        if own_id:
            tokens.add(own_id)
        hit = None
        for token in tokens:
            hit = resolutions_map.get(token)
            if hit:
                break
        if hit:
            entry: dict = {
                "resolved_this_session": True,
                "resolver_id": hit["resolver_id"],
            }
            disposition = hit.get("disposition")
            if disposition:
                entry["disposition"] = disposition
            elif hit.get("resolver_type") == "decision":
                # Decisions without explicit disposition are adoptions
                entry["disposition"] = DISPOSITION_ADOPTED
            statuses.append(entry)
        else:
            statuses.append({"resolved_this_session": False})
    latest["try_status"] = statuses

    kept = [
        (t, s)
        for t, s in zip(latest["try"], statuses, strict=True)
        if s.get("disposition") != DISPOSITION_DROPPED
    ]
    latest["try"] = [t for t, _ in kept]
    latest["try_status"] = [s for _, s in kept]
