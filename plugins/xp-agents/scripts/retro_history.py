#!/usr/bin/env python3
"""Retrospective history gathering.

Reads the last N retrospective JSON files from ${SMM_DIR}/retrospectives/
and slims them to content strings for the retro analyst agent.
"""

import json
from pathlib import Path

MAX_RETRO_HISTORY = 2
MAX_RETRO_FILE_SIZE = 1_048_576  # 1 MB


def gather_retro_history(smm_dir: Path, limit: int = MAX_RETRO_HISTORY) -> list[dict]:
    """Read the last N retrospective JSON files, slimmed to content only.

    Strips event_refs, values, xp_value — the retro agent only needs
    the content strings for trend detection (recurring fixes, adopted tries).
    """
    retro_dir = smm_dir / "retrospectives"
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
                for field in ("keep", "fix", "try"):
                    items = data.get(field, [])
                    slimmed[field] = [
                        item.get("content", item) if isinstance(item, dict) else item
                        for item in items
                    ]
                result.append(slimmed)
        except (json.JSONDecodeError, OSError):
            continue
    return result
