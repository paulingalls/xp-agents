#!/usr/bin/env python3
"""Which stories predate the manual-acceptance-shape rule.

Authoring forbids `command`/`commands` on a `type: manual` acceptance block
(see _acceptance_execution). Sprints written before that rule may already
carry one, and validate_sprint walks EVERY story — so without an exemption a
single stored block would refuse every later, unrelated write on that sprint
(a promotion, an accept-path amendment) with an error naming a story the
operator never touched.

Split out of sprint_store.py for the file-size cap: this is one cohesive
question (derive the exemption set from disk), and it is the only place in
the store that reads the stored sprint as raw bytes rather than as a loaded,
schema-valid document.
"""

import json
from pathlib import Path

from sprint_schema import SPRINT_FILENAME


def is_manual_with_command(block: object) -> bool:
    """True for an acceptance block the authoring rule now forbids."""
    return (
        isinstance(block, dict)
        and block.get("type") == "manual"
        and ("command" in block or "commands" in block)
    )


def grandfathered_story_ids(smm_dir: Path, data: dict) -> frozenset[str]:
    """Story ids whose manual+command acceptance block predates the rule.

    A story is exempt only when the block ALREADY ON DISK for that id is
    manual+command AND the incoming block is unchanged. Edit that block and
    you must fix it; leave it alone and every other edit proceeds.

    Reads disk directly rather than via load_sprint: the stored sprint may
    legitimately be one the current schema would reject, and the question
    here is only "what was already there".

    Fails CLOSED. Missing, symlinked, unreadable or corrupt sprint → no proof
    anything was grandfathered → empty set → the rule applies to every story.
    An exemption that failed open would be a bypass reachable by deleting a
    file.
    """
    path = smm_dir / SPRINT_FILENAME
    if path.is_symlink():
        return frozenset()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(stored, dict) or not isinstance(stored.get("stories"), list):
        return frozenset()

    stored_blocks = {
        s["id"]: s.get("acceptance_execution")
        for s in stored["stories"]
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    incoming = data.get("stories")
    if not isinstance(incoming, list):
        return frozenset()
    return frozenset(
        s["id"]
        for s in incoming
        if isinstance(s, dict)
        and isinstance(s.get("id"), str)
        and is_manual_with_command(stored_blocks.get(s["id"]))
        and s.get("acceptance_execution") == stored_blocks[s["id"]]
    )
