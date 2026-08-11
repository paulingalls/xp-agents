#!/usr/bin/env python3
"""The two records a review cycle keeps, and the checkout each belongs to.

Split out of `markers.py` when it passed its sub-cap, and split from EACH
OTHER because they are keyed on different checkouts:

  - the FLAGS say whether this session has reviewed yet, so they are keyed on
    the session that ran the review (`identity.review_flags_key`);
  - the WATERMARK says which commit the last review measured from, and its
    only consumer diffs `{sha}..HEAD` inside a specific repo, so it is keyed
    on the repo a commit lands in (`identity.review_watermark_key`).

Held in one file, every site that touched both had to pick one owner for both.
The four sites that READ or WRITE both picked the repo (three of them land a
commit and now share `end_review_cycle`; the fourth is the gate), the seven
flag-only sites picked the session,
and they agree only while a session commits into its own checkout. `git -C
<other-repo> commit` is when they do not, and there the gate read a record
/xp-quality-review never writes — a block no rerun could clear, because every
writer kept writing the other one. Pinned in test_review_record_owners.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from markers import (
    REVIEW_CYCLE,
    REVIEW_WATERMARK,
    marker_read,
    marker_write,
)

_DEFAULT_REVIEW_FLAGS: dict = {
    "simplify_done": False,
    "quality_review_done": False,
}

_REVIEW_FLAGS = frozenset(_DEFAULT_REVIEW_FLAGS)

_WATERMARK_FIELD = "last_review_commit"


def read_review_flags(smm_dir: Path, agent_id: str) -> dict:
    """Read the review flags, returning defaults if missing.

    A record written before the split carries a `last_review_commit` key too.
    It is not a flag and never becomes one here; `read_review_watermark` is
    what still reads it, until the first commit in that checkout writes the
    watermark's own record.
    """
    data = marker_read(smm_dir, REVIEW_CYCLE, agent_id)
    if not isinstance(data, dict):
        return dict(_DEFAULT_REVIEW_FLAGS)
    return dict(_DEFAULT_REVIEW_FLAGS) | data


def write_review_flags(smm_dir: Path, agent_id: str, data: dict) -> None:
    """Write the review flags marker."""
    marker_write(smm_dir, REVIEW_CYCLE, data, agent_id)


def clear_review_flags(smm_dir: Path, agent_id: str) -> None:
    """End the session's review cycle: every flag back to False.

    Carries a PRE-SPLIT record's sha across the reset. `read_review_watermark`
    still falls back to it, and the two keys are not the same checkout — under
    `git -C <other>` this clears one while the watermark is stamped on another,
    so writing the bare defaults would drop the only sha an upgrading install
    has and leave the fallback nothing to find. Inert once that checkout's own
    watermark record exists, since the new record is read first.
    """
    data = dict(_DEFAULT_REVIEW_FLAGS)
    existing = marker_read(smm_dir, REVIEW_CYCLE, agent_id)
    if isinstance(existing, dict):
        carried = existing.get(_WATERMARK_FIELD, "")
        if isinstance(carried, str) and carried:
            data[_WATERMARK_FIELD] = carried
    write_review_flags(smm_dir, agent_id, data)


def set_review_flag(
    smm_dir: Path, agent_id: str, flag: str, value: bool = True
) -> None:
    """Set a single review flag (read-modify-write)."""
    if flag not in _REVIEW_FLAGS:
        raise ValueError(f"Invalid review cycle flag: {flag!r}")
    data = read_review_flags(smm_dir, agent_id)
    data[flag] = value
    write_review_flags(smm_dir, agent_id, data)


def read_review_watermark(smm_dir: Path, agent_id: str) -> str:
    """The commit the last review measured from, or "" when there is none.

    A sha from any other repo makes the gate's `{sha}..HEAD` diff fail; the
    count then degrades to the legs that did answer rather than to zero, which
    is `commits.get_code_files_for_review`'s rule and pinned there.

    Falls back to the PRE-SPLIT record, where every install that upgrades
    across the split still holds its sha. The flags kept their file and
    migrated for free; without this the watermark would read "" once per
    checkout, drop the `{sha}..HEAD` leg, and let through the commit the old
    record would have blocked. Pinned in test_review_record_owners.py.
    """
    for marker in (REVIEW_WATERMARK, REVIEW_CYCLE):
        data = marker_read(smm_dir, marker, agent_id)
        if isinstance(data, dict):
            value = data.get(_WATERMARK_FIELD, "")
            if isinstance(value, str) and value:
                return value
    return ""


def write_review_watermark(smm_dir: Path, agent_id: str, commit_hash: str) -> None:
    """Advance the target repo's watermark to a commit that just landed."""
    marker_write(smm_dir, REVIEW_WATERMARK, {_WATERMARK_FIELD: commit_hash}, agent_id)


def end_review_cycle(
    smm_dir: Path, watermark_key: str, flags_key: str, commit_hash: str
) -> None:
    """What a landed commit does to both records — the three commit sites' one door.

    Two files, so no write is atomic across them, and the ORDER is the whole
    reason this is one function: clearing the flags FIRST means an interrupted
    pair leaves the gate armed against a stale watermark (over-counts by one
    review), never advanced against a stale `quality_review_done` (counts
    nothing and blocks nothing). Pinned in test_markers_review.py.
    """
    clear_review_flags(smm_dir, flags_key)
    write_review_watermark(smm_dir, watermark_key, commit_hash)


def review_mid_cycle(smm_dir: Path, agent_id: str) -> bool:
    """True when a review cycle is mid-flight for ``agent_id``.

    Mid-cycle = /code-review (or /simplify) has set ``simplify_done`` but
    /xp-quality-review has not yet set ``quality_review_done``. One home for
    the predicate, so the Stop gates that defer on it cannot drift apart.

    Load-bearing invariant: a standalone self-find review sets
    ``quality_review_done`` WITHOUT ``simplify_done`` — that is a COMPLETED
    review, not mid-cycle, so it returns False.
    """
    flags = read_review_flags(smm_dir, agent_id)
    return bool(flags.get("simplify_done")) and not flags.get("quality_review_done")
