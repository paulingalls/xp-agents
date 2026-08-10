#!/usr/bin/env python3
"""Which stories/milestones predate the manual-acceptance-shape rule.

Authoring forbids `command`/`commands` on a `type: manual` acceptance block
(see _acceptance_execution). Sprints/plans written before that rule may
already carry one, and validate_sprint/validate_plan walk EVERY story/
milestone — so without an exemption a single stored block would refuse
every later, unrelated write on that document with an error naming an item
the operator never touched.

Split out of sprint_store.py for the file-size cap: this is one cohesive
question (derive the exemption set from disk), and it is the only place
that reads the stored document as raw bytes rather than as a loaded,
schema-valid document.
"""

import json
from pathlib import Path
from typing import TypeVar

from execution_plan_schema import PLAN_FILENAME
from sprint_schema import SPRINT_FILENAME

_K = TypeVar("_K", str, int)


def is_manual_with_command(block: object) -> bool:
    """True for an acceptance block the authoring rule now forbids."""
    return (
        isinstance(block, dict)
        and block.get("type") == "manual"
        and ("command" in block or "commands" in block)
    )


def _grandfathered_keys(
    smm_dir: Path,
    data: dict,
    *,
    filename: str,
    list_field: str,
    key_field: str,
    key_type: type[_K],
) -> frozenset[_K]:
    """Shared fail-closed core for grandfathered_story_ids/_milestone_numbers.

    An item is exempt only when the block ALREADY ON DISK for that key is
    manual+command AND the incoming block is unchanged. Edit that block and
    you must fix it; leave it alone and every other edit proceeds.

    Reads disk directly rather than via a loader: the stored document may
    legitimately be one the current schema would reject, and the question
    here is only "what was already there".

    Fails CLOSED. Missing, symlinked, unreadable or corrupt document → no
    proof anything was grandfathered → empty set → the rule applies to
    every item. An exemption that failed open would be a bypass reachable
    by deleting a file.
    """
    path = smm_dir / filename
    if path.is_symlink():
        return frozenset()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(stored, dict) or not isinstance(stored.get(list_field), list):
        return frozenset()

    stored_blocks = {
        item[key_field]: item.get("acceptance_execution")
        for item in stored[list_field]
        if isinstance(item, dict) and isinstance(item.get(key_field), key_type)
    }
    incoming = data.get(list_field)
    if not isinstance(incoming, list):
        return frozenset()
    return frozenset(
        item[key_field]
        for item in incoming
        if isinstance(item, dict)
        and isinstance(item.get(key_field), key_type)
        and is_manual_with_command(stored_blocks.get(item[key_field]))
        and item.get("acceptance_execution") == stored_blocks[item[key_field]]
    )


def grandfathered_story_ids(smm_dir: Path, data: dict) -> frozenset[str]:
    """Story ids whose manual+command acceptance block predates the rule."""
    return _grandfathered_keys(
        smm_dir,
        data,
        filename=SPRINT_FILENAME,
        list_field="stories",
        key_field="id",
        key_type=str,
    )


def grandfathered_milestone_numbers(smm_dir: Path, data: dict) -> frozenset[int]:
    """Milestone numbers whose manual+command acceptance block predates the
    rule. Sibling of grandfathered_story_ids — see that function's docstring
    for the exemption semantics; the two differ only in which document and
    key they read.
    """
    return _grandfathered_keys(
        smm_dir,
        data,
        filename=PLAN_FILENAME,
        list_field="milestones",
        key_field="number",
        key_type=int,
    )
