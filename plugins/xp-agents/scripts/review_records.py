#!/usr/bin/env python3
"""The records a review cycle keeps, and the checkout each belongs to.

Split out of `markers.py` when it passed its sub-cap, and split from EACH
OTHER because they are keyed on different checkouts:

  - the FLAGS say whether this session has reviewed yet, so they are keyed on
    the session that ran the review (`identity.review_flags_key`);
  - the WATERMARK says which commit the last review measured from, and its
    only consumer diffs `{sha}..HEAD` inside a specific repo, so it is keyed
    on the repo a commit lands in (`identity.review_watermark_key`);
  - the COVERAGE says which paths the last review looked at. They are
    repo-relative, and the same path in another checkout is other work, so it
    is keyed on the repo as well — under the session key a `git -C <other>`
    commit would have matched them by name and exempted a file no review
    opened.

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
    REVIEW_COVERAGE,
    REVIEW_CYCLE,
    REVIEW_WATERMARK,
    marker_consume,
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


_COVERAGE_PATHS = "paths"
_COVERAGE_AGE = "commits_survived"
_COVERAGE_HEAD = "written_at"

# A review's coverage outlives the commit that ends its own cycle, and is spent
# by the next one. Two, not one: the reviewed work lands first, so spending it
# there would leave nothing for the fixes — the case this exists for. Two, not
# more: past that the set is stale, and a file a review once glanced at would
# stay exempt while it was edited freely.
_COVERAGE_MAX_AGE = 2


def write_review_coverage(
    smm_dir: Path, agent_id: str, paths: list[str], head: str = ""
) -> None:
    """Record the code files a completed review looked at.

    REPLACES any older set rather than merging: coverage is the LAST review's
    scope, and a union would forgive files the current review never opened. The
    age restarts with it, so a fresh review always covers its own fixes.

    ``head`` is the commit the review was recorded at, and is what lets
    `read_review_coverage` expire a record no commit site ever spent. Optional
    because a caller that cannot resolve one is better off writing coverage
    without it than not at all: the write-driven ageing below still applies,
    which is exactly the behaviour before this field existed.
    """
    record = {_COVERAGE_PATHS: sorted(set(paths)), _COVERAGE_AGE: 0}
    if head:
        record[_COVERAGE_HEAD] = head
    marker_write(smm_dir, REVIEW_COVERAGE, record, agent_id)


def read_review_coverage(smm_dir: Path, agent_id: str, cwd: str = "") -> set[str]:
    """The paths recorded for the last review, expired if HEAD has moved on.

    Two expiries, because there are two ways a commit can land. The
    WRITE-driven one is `_age_review_coverage`, on the commit sites' path. It
    fails open on its own: a commit that reaches no commit site — an xp-
    subagent's, which `is_xp_agent` skips — never spends the record, so its
    paths would stay exempt with no bound, and a later session could rewrite
    every one of them and commit unreviewed.

    A counter cannot close that, because the write that fails to age is the
    same one that fails to advance the watermark: nothing in the SMM moved.
    HEAD did, so the second expiry asks git directly — how many commits since
    the record was written — and drops it at the same cap. `..HEAD` counts only
    what is reachable from here, so a branch switch reads as distance rather
    than as history to forgive.

    ``cwd`` is what makes that possible and is optional for the callers who
    have no repo to name; without it, or without a recorded commit, or when git
    cannot answer, the record reads as it stands — the pre-existing behaviour,
    kept rather than expiring coverage on an unanswerable question.

    Empty on anything unreadable — a malformed record forgives nothing, which
    fails toward one extra review rather than toward an unreviewed commit.
    """
    data = marker_read(smm_dir, REVIEW_COVERAGE, agent_id)
    if not isinstance(data, dict):
        return set()
    paths = data.get(_COVERAGE_PATHS)
    if not isinstance(paths, list):
        return set()
    if _commits_since_write(data, cwd) >= _COVERAGE_MAX_AGE:
        return set()
    return {p for p in paths if isinstance(p, str) and p}


def _commits_since_write(data: dict, cwd: str) -> int:
    """Commits landed since the coverage record was written, or 0 if unknown.

    0 is "do not expire on this evidence" — the answer for a record with no
    recorded commit, a caller with no repo, and a git that could not answer
    (a rewritten or pruned sha, a detached state). Every one of those is an
    absence of information, and the write-driven ageing still governs there;
    expiring on them would drop coverage the review genuinely earned.

    `commits` is imported lazily: `review_records` is on the import path of
    nearly every hook, and only this read needs git.
    """
    head = data.get(_COVERAGE_HEAD)
    if not cwd or not isinstance(head, str) or not head:
        return 0
    import commits

    out = commits.count_commits_since(cwd, head)
    return out if out is not None else 0


def uncovered_count(changed: list[str], covered: set[str]) -> int:
    """How many of ``changed`` the last review did NOT look at.

    Set arithmetic only — it does no code/doc classification, because its
    caller has already filtered to code files. Pinned in
    test_review_coverage.py so a caller cannot assume it filters.
    """
    return sum(1 for path in changed if path not in covered)


def _age_review_coverage(smm_dir: Path, agent_id: str) -> None:
    """Spend one commit's worth of coverage, dropping the record at the cap."""
    data = marker_read(smm_dir, REVIEW_COVERAGE, agent_id)
    if not isinstance(data, dict):
        return
    age = data.get(_COVERAGE_AGE)
    age = age + 1 if isinstance(age, int) else _COVERAGE_MAX_AGE
    if age >= _COVERAGE_MAX_AGE:
        marker_consume(smm_dir, REVIEW_COVERAGE, agent_id)
        return
    marker_write(smm_dir, REVIEW_COVERAGE, {**data, _COVERAGE_AGE: age}, agent_id)


def end_review_cycle(
    smm_dir: Path, watermark_key: str, flags_key: str, commit_hash: str
) -> None:
    """What a landed commit does to all three records — the commit sites' one door.

    Three files, so no write is atomic across them, and the ORDER is the whole
    reason this is one function: clearing the flags FIRST means an interrupted
    pair leaves the gate armed against a stale watermark (over-counts by one
    review), never advanced against a stale `quality_review_done` (counts
    nothing and blocks nothing). Ageing coverage LAST follows the same rule —
    an interrupt there leaves it unspent, so the gate forgives one commit too
    many rather than blocking fixes it was built to let through. Pinned in
    test_markers_review.py and test_review_coverage.py.
    """
    clear_review_flags(smm_dir, flags_key)
    write_review_watermark(smm_dir, watermark_key, commit_hash)
    _age_review_coverage(smm_dir, watermark_key)


def review_mid_cycle(smm_dir: Path, agent_id: str) -> bool:
    """True when a review cycle is mid-flight for ``agent_id``.

    Mid-cycle = /code-review (or /simplify) has set ``simplify_done`` but the
    quality review has not yet set ``quality_review_done`` — which happens when
    the xp-code-reviewer agent /xp-quality-review spawns RETURNS, not when the
    skill is invoked. One home for the predicate, so the Stop gates that defer
    on it cannot drift apart.

    Load-bearing invariant: a standalone self-find review sets
    ``quality_review_done`` WITHOUT ``simplify_done`` — that is a COMPLETED
    review, not mid-cycle, so it returns False.
    """
    flags = read_review_flags(smm_dir, agent_id)
    return bool(flags.get("simplify_done")) and not flags.get("quality_review_done")
