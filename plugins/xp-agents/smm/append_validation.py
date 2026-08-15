#!/usr/bin/env python3
"""Validation primitives shared across the SMM append/read path.

Three independent helpers that don't depend on any other smm/ module:

- validate_smm_dir: ownership + world-writable check on the SMM directory.
  Run before any append to make sure we're not writing into a hostile
  directory (symlink swap, world-writable, or a path that isn't ours).
- validate_agent_id: regex allowlist for agent_id strings. Agent ids
  flow into filenames (.watermark-<id>) and JSON event content, so we
  reject anything that could escape either context.
- parse_jsonl: tolerant JSONL parser. Skips blanks, malformed lines,
  and non-dict values silently — used by every reader of events.jsonl
  so they all see the same canonical view.

Extracted from _append_impl.py to keep that module under the 500-line
size budget. Tests live in tests/smm/test_append_safety.py and
tests/engine/test_parse.py.
"""

import json
import os
import re
from pathlib import Path

# `\Z`, not `$`: `$` also matches just before a FINAL newline, so `"agent\n"`
# cleared this allowlist. Agent ids are interpolated into marker filenames
# (`.watermark-<id>`), where a trailing newline names a file no other caller
# reads. Pinned in tests/smm/test_append_safety.py.
_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_:\-]+\Z")


def validate_smm_dir(smm_dir: Path) -> None:
    """Validate SMM directory exists, is owned by us, not world-writable."""
    if not smm_dir.exists():
        raise ValueError(f"SMM directory does not exist: {smm_dir}")
    st = smm_dir.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f"SMM directory not owned by current user: {smm_dir}")
    if st.st_mode & 0o002:
        raise ValueError(f"SMM directory is world-writable: {smm_dir}")


def is_valid_agent_id(agent_id: str) -> bool:
    """The same allowlist as a question rather than an assertion.

    For the caller that can DEGRADE on a bad id instead of failing — a resolver
    turning a path into a marker key, where raising takes down a hook that is
    supposed to be advisory. Pinned in test_review_record_owners.py.
    """
    return bool(agent_id) and bool(_AGENT_ID_RE.match(agent_id))


def validate_agent_id(agent_id: str) -> None:
    """Reject agent IDs that don't match the allowlist pattern."""
    if not agent_id:
        raise ValueError("agent_id must not be empty")
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


def parse_jsonl(raw: str) -> tuple[list[dict], int]:
    """Parse JSONL text into dicts. Returns (events, skipped_count).

    Skips blank lines, malformed JSON, and non-dict values silently.
    Canonical JSONL parser — all events.jsonl readers go through this.
    """
    events: list[dict] = []
    skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
            else:
                skipped += 1
        except json.JSONDecodeError:
            skipped += 1
    return events, skipped
