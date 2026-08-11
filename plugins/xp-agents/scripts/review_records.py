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
The four commit sites picked the repo, the seven flag sites picked the session,
and they agree only while a session commits into its own checkout. `git -C
<other-repo> commit` is when they do not, and there the gate read a record
/xp-quality-review never writes — a block no rerun could clear, because every
writer kept writing the other one. Pinned in test_review_record_owners.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

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

    A record written before the split carries a `last_review_commit` key too;
    it is inert here, and the first commit in that checkout stops writing it.
    """
    data = marker_read(smm_dir, REVIEW_CYCLE, agent_id)
    if not isinstance(data, dict):
        return dict(_DEFAULT_REVIEW_FLAGS)
    return dict(_DEFAULT_REVIEW_FLAGS) | data


def write_review_flags(smm_dir: Path, agent_id: str, data: dict) -> None:
    """Write the review flags marker."""
    marker_write(smm_dir, REVIEW_CYCLE, data, agent_id)


def clear_review_flags(smm_dir: Path, agent_id: str) -> None:
    """End the session's review cycle: every flag back to False."""
    write_review_flags(smm_dir, agent_id, dict(_DEFAULT_REVIEW_FLAGS))


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

    A sha from any other repo makes the gate's `{sha}..HEAD` diff fail, and
    the changed-file count then collapses silently to the staged set — the
    gate stops firing rather than firing wrongly.
    """
    data = marker_read(smm_dir, REVIEW_WATERMARK, agent_id)
    if not isinstance(data, dict):
        return ""
    value = data.get(_WATERMARK_FIELD, "")
    return value if isinstance(value, str) else ""


def write_review_watermark(smm_dir: Path, agent_id: str, commit_hash: str) -> None:
    """Advance the target repo's watermark to a commit that just landed."""
    marker_write(smm_dir, REVIEW_WATERMARK, {_WATERMARK_FIELD: commit_hash}, agent_id)


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
