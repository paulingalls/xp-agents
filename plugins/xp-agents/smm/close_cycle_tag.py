#!/usr/bin/env python3
"""Tag a concern with the close cycle that was running when it was raised.

The merge gate counts open high-severity concerns before letting a close
merge, and has to know which of them are ABOUT this close. Inferring that from
the `files` a concern recorded means a stale or wrong path silently EXCLUDES a
concern from the one gate that exists not to miss it. This records the answer
instead, at the moment the concern is written: the close preloads persist their
cycle id to a session-scoped marker, and the appender reads it.

Lives beside the appender rather than inside it for two reasons: `_append_impl`
is at its size ceiling, and this is one cohesive rule (read the marker, decide
whether to stamp) with one caller — `_append_impl.main()`.

Deliberately NOT reached from `append_event`, the shared write path:

- At that layer the transient TDD test-failure concerns the hooks write would be
  tagged too, and `smm_count` carves those out of a scoped gate count by their
  tag being ABSENT. Tagging them would re-break a sibling teammate's red test
  false-aborting a clean close. Hook-written concerns (which go through
  `_common.append_safe`) therefore stay untagged and keep the files-relevance
  fallback — a stated limit of this tagging, not full coverage.

Nothing here imports `scripts/`: this is the appender's PRE-WRITE path, and the
one existing scripts/ import in that file (the post-write duplicate-debt probe)
is wrapped in a bare `except` — the wrong pattern for a step whose failure has
to be visible. `marker_names` and `session_scope` exist to be reachable from
here; see their module docstrings.
"""

import sys
from pathlib import Path

import marker_names
import session_scope
from event_schema import EVENT_TYPE_CONCERN, METADATA_KEY_CLOSE_CYCLE_ID

# THE 12-hex id pattern in this codebase. A close-cycle id comes from the same
# generator an event id does, so it is validated by the same regex rather than
# by a second hand-rolled one.
from smm_schema import EVENT_ID_RE


def _unusable_marker(path: Path, problem: str) -> None:
    """Report a marker that is present but yields no id, and return None.

    This is the one fail-closed branch that must be VISIBLE. "No marker" means
    no close is running, which is the normal state for most of a session; a
    marker that EXISTS but cannot be used means a close armed itself and
    something went wrong afterwards, and silently dropping the tag would look
    identical to the ordinary case. stderr, never stdout: the appender's stdout
    contract is the new event's id and nothing else.
    """
    print(
        f"append: {path.name} {problem}, so this concern is not tagged with a "
        "close cycle (it still counts toward every close gate)",
        file=sys.stderr,
    )
    return None


def read_close_cycle_id(smm_dir: Path) -> str | None:
    """The id of the close cycle running in THIS session, or None.

    Session-scoped because the SMM dir is shared across worktrees: one file
    would be last-writer-wins between two concurrent closes, which would both
    hide the first close's concerns and tag a bystander's concern into a close
    it has nothing to do with.

    Fails closed on every branch. Absent, empty, unreadable, a symlink (which
    could name a file outside the SMM dir — the same refusal
    `markers.marker_read` makes) or not a well-formed id all return None, and
    None means the concern keeps exactly the behaviour it has today.
    """
    path = smm_dir / session_scope.scoped_name(
        marker_names.CLOSE_CYCLE_ID, session_scope.resolve_session_id()
    )
    if path.is_symlink():
        return _unusable_marker(path, "is a symlink")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return _unusable_marker(path, f"could not be read ({exc})")
    value = raw.strip()
    if not value:
        return _unusable_marker(path, "is empty")
    if not EVENT_ID_RE.match(value):
        return _unusable_marker(path, "does not hold a 12-hex id")
    return value


def stamp(smm_dir: Path, event: dict) -> None:
    """Set `metadata.close_cycle_id` on a concern raised during a close.

    Only concerns: the gate counts concerns, and a status or debt event
    carrying the key would be read as a close-cycle record it is not.

    An explicitly supplied id WINS. Both close reviewers pass their cycle id
    deliberately, and letting a stale or foreign marker overwrite a correct
    explicit tag would be the fail-open choice. A blank or non-string value is
    not a decision, though — `smm_count` excludes any concern whose tag is
    present and unequal to the gated cycle, so an empty tag would drop the
    concern from EVERY close; replacing it can only move it back into a count.
    """
    if event.get("type") != EVENT_TYPE_CONCERN:
        return
    metadata = event.get("metadata")
    explicit = metadata.get(METADATA_KEY_CLOSE_CYCLE_ID) if metadata else None
    if isinstance(explicit, str) and explicit.strip():
        return
    cycle_id = read_close_cycle_id(smm_dir)
    if cycle_id is None:
        return
    if not isinstance(metadata, dict):
        metadata = {}
        event["metadata"] = metadata
    metadata[METADATA_KEY_CLOSE_CYCLE_ID] = cycle_id
