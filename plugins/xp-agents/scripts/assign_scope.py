#!/usr/bin/env python3
"""The ASSIGN_PENDING marker's payload: which stories the assign gate is armed for.

One module because it is ONE contract with two ends — the writer (the
plan-review handler in subagent_stop) and the reader (the assign gate's
predicate in lead_gates) — which must not drift apart:

    sprint=<sprint_id>;stories=<id>,<id>,...

Extracted from markers.py rather than added to it: markers.py is the generic
marker infrastructure (MarkerDef, path/read/write/consume) plus a few
one-or-two-line payload helpers, and this contract's rationale alone is longer
than any of them — it took that file to 521 lines, past the 500 cap. Imports go
DOWN: this module depends on markers, never the reverse.

Scoped-vs-legacy is a SHAPE question answered by a fixed sentinel, never
INFERRED from the content. Markers written before the scope existed hold a bare
agent id, and every content-sniffing rule misreads one side or the other: "more
than one token" makes a one-story armed set — the common frontier shape — read
as legacy, leaving the scope inert exactly where it matters; "contains a dash"
flips `xp-plan-reviewer` to scoped; and story ids are unvalidated free strings
(sprint_schema only checks isinstance(str)), so "looks like an id in
sprint.json" is both spoofable and wrong after a sprint rollover.

The sprint id is recorded because story ids REPEAT every sprint and nothing
sweeps this marker at a sprint boundary — a bare `story-005` armed last sprint
would otherwise match a different `story-005` this one. Same hazard
lead_gates._story_is_spawned defends against on the worktree side.

The marker stays a "text" marker deliberately. Under a "json" MarkerDef
marker_exists would validate the content, so a legacy text payload would read as
ABSENT and silently disarm the gate for everyone still holding one.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from markers import ASSIGN_PENDING, marker_read

_PREFIX = "sprint="
_SEP = ";stories="
_LIST_SEP = ","
# What the encoder writes when it cannot record a faithful scope: a payload
# with NO sentinel, which the reader collapses to None and the caller then
# treats as unscoped — armed, exactly as before scoping existed.
_UNENCODABLE = "unscoped"


def format_assign_scope(sprint_id: str, story_ids: list[str]) -> str:
    """Encode the stories an assign marker is being armed for.

    The SAME "story ids are unvalidated free strings" fact the sentinel exists
    for also binds the ENCODER: an id carrying a delimiter cannot survive the
    round trip, and an id that decodes to FRAGMENTS matches no story — which
    empties the reader's intersection, and an empty intersection is the assign
    predicate's False, which DELETES a marker the lead still needs. A blank id
    is the same hazard by omission: the reader drops empty tokens, so the story
    silently leaves the armed set.

    Neither is escaped, because a scope is a hint the gate can do without: any
    unencodable id drops the WHOLE scope to the sentinel-less payload, which
    reads as legacy and stays armed. Fail toward blocking, never toward a
    consume.
    """
    if any(not sid or _LIST_SEP in sid or _SEP in sid for sid in story_ids):
        return _UNENCODABLE
    return f"{_PREFIX}{sprint_id}{_SEP}{_LIST_SEP.join(story_ids)}"


def read_assign_scope(smm_dir: Path, sprint_id: str) -> frozenset[str] | None:
    """The story ids ASSIGN_PENDING was armed for, or None for "no usable scope".

    None is the FAIL-CLOSED answer and every untrustworthy read collapses to
    it: the caller must then fall back to its unscoped behavior, which keeps
    the gate armed. It is returned when the marker is missing, a symlink or
    unreadable (marker_read already covers all three), when the payload
    carries no sentinel (armed before this format existed, or armed for ids
    the encoder could not round-trip), when it names a DIFFERENT sprint, and
    when it records an EMPTY set.

    The empty set matters most: read as "nothing is armed" it would let the
    predicate delete a marker the lead still needs. It means the writer told
    us nothing, not that there is nothing to do.

    *sprint_id* is the CURRENT sprint's id; an empty one cannot identify a
    sprint, so it never establishes a match.
    """
    content = marker_read(smm_dir, ASSIGN_PENDING)
    if not isinstance(content, str) or not content.startswith(_PREFIX):
        return None
    armed_sprint, sep, ids = content[len(_PREFIX) :].partition(_SEP)
    if not sep or not sprint_id or armed_sprint != sprint_id:
        return None
    story_ids = frozenset(sid for sid in ids.split(_LIST_SEP) if sid)
    return story_ids or None
