#!/usr/bin/env python3
"""The sprint verify RECORD: what goes into it, how it shows, how it reads back.

The half of ``verify_acceptance --sprint`` that never runs anything. One
function turns a sprint document into the list of items to run; one turns the
results into the operator's PASS/FAIL matrix; two read the emitted verify event
back out and describe it. Nothing here shells out, reads a clock, or decides an
exit code — running and bounding stayed in ``verify_acceptance``.

The read side lives here rather than beside the runner because the event has
TWO consumers — the status CLI and the in-process merge gate — and a shared
description is what stops them drifting into reporting the same event
differently. The gate once refused a merge naming nothing at all, because it
built its own message from half the record.

Extracted when the batch-total budget would have pushed ``verify_acceptance.py``
past this repo's file-size band, above which a module may not grow further
without shrinking back under it first. Splitting at the commit that crosses the
line is cheaper than crossing it and extracting under that constraint later.

Imports DOWN only; ``verify_acceptance`` imports these names, never the reverse.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
from _acceptance_execution import extract_commands
from event_schema import (
    EVENT_TYPE_SPRINT,
    SPRINT_ACTION_VERIFY,
    VERIFY_STATUS_NONE,
)

# Author of every sprint-verify event, and the filter both readers select on.
_AGENT_ID = "verify-acceptance"

# Story-level acceptance_execution carries no surface; bucket it here.
_STORY_SURFACE = "(story)"

# A READER-side status with no event behind it: the sprint carries
# verify-bearing items and nothing has recorded a result for them. Deliberately
# NOT an `event_schema.VERIFY_STATUS_*` value — nothing appends it, and the
# append-time enum would reject it if something tried.
VERIFY_REPORT_UNVERIFIED = "unverified"

# A deferred story's deliverable is intentionally not built, so its acceptance
# commands would go RED on the expected-missing artifact and block the close of
# legitimately-shipped work (hit live closing sprint-121). --sprint skips only
# deferred — `done` stories must still verify, so this is NOT the terminal set.
_DEFERRED_STATUS = "deferred"


def _gather_sprint_items(
    sprint: dict,
) -> list[tuple[str, int | None, str | None, str | None, bool]]:
    """Every verify-bearing command across the sprint.

    Each tuple is (story_id, ac_idx, surface, command, na). Object-shaped
    acceptance_criteria items carrying a command/commands block contribute one
    tuple per command with their declared surface (na=False). The story-level
    acceptance_execution contributes with ac_idx=None and surface from the block
    (usually absent → grouped under the story bucket): a block that carries a
    command/commands is expanded to run tuples; a command-less block (only a
    manual block may be command-less — see the schema) contributes ONE N/A
    sentinel (command=None, na=True) so the story stays visible in the matrix
    without being shelled. Deferred stories, string ACs, and stories with no
    verify commands contribute nothing.
    """
    items: list[tuple[str, int | None, str | None, str | None, bool]] = []
    for story in sprint.get("stories", []):
        if story.get("status") == _DEFERRED_STATUS:
            # Skip deferred stories: their deliverable is intentionally absent,
            # so verifying them yields a false RED that blocks the close.
            continue
        sid = story.get("id", "?")
        for idx, ac in enumerate(story.get("acceptance_criteria", [])):
            if isinstance(ac, dict) and ("command" in ac or "commands" in ac):
                for cmd in extract_commands(ac):
                    items.append((sid, idx, ac.get("surface"), cmd, False))
        ae = story.get("acceptance_execution")
        if ae:
            if "command" in ae or "commands" in ae:
                for cmd in extract_commands(ae):
                    items.append((sid, None, ae.get("surface"), cmd, False))
            else:
                # Command-less block (a manual, prose/steps-only check): one N/A
                # sentinel so it shows in the matrix without ever being shelled.
                items.append((sid, None, ae.get("surface"), None, True))
    return items


def _print_matrix(rows: list[dict]) -> None:
    """Print the result rows grouped by surface, one PASS/FAIL line each."""
    by_surface: dict[str, list[dict]] = {}
    for r in rows:
        by_surface.setdefault(r["surface"] or _STORY_SURFACE, []).append(r)
    for surface in sorted(by_surface):
        print(f"Surface: {surface}")
        for r in by_surface[surface]:
            ac = f"ac{r['ac_idx']}" if r["ac_idx"] is not None else "ae"
            if r.get("na"):
                print(f"  [N/A] {r['story']} {ac}  {r['command']}")
                continue
            if r.get("skipped"):
                # A third outcome, and it must not read as either of the other
                # two: the item did not pass, and it did not fail — it never
                # ran. The seconds live in the caller's stderr line, which is
                # where the actionable message belongs; this row only says
                # WHICH items were not reached.
                print(f"  [SKIP] {r['story']} {ac}  {r['command']}  (not run)")
                continue
            rc = r["returncode"]
            mark = "PASS" if rc == 0 else "FAIL"
            print(f"  [{mark}] {r['story']} {ac}  {r['command']}  (exit {rc})")


def verify_report(smm_dir: Path, sprint: dict) -> tuple[str, list[dict], list[dict]]:
    """The status a READER should act on, which is not always the one recorded.

    "No verify event" has two meanings and only one of them is green. A sprint
    whose acceptance is all prose has nothing to run, so `none` is the honest
    answer and the close gate proceeds. A sprint that DOES carry verify-bearing
    items and still has no event was never verified — and reading that as `none`
    made the absence of evidence pass as evidence of absence, at a gate whose
    whole job is to hold the merge until the rerun says green.

    That absence is reachable, not theoretical: the rerun is launched through a
    harness-bounded tool call, and a run killed by the OUTER bound is killed
    before it can append. Its per-command and batch bounds cannot save it —
    they are larger than the bound of the only production caller — so the one
    thing that stays under this project's control is refusing to read the
    silence as green. `--force-close` remains the documented override.

    `_gather_sprint_items` is the same enumeration the runner uses, so the two
    cannot disagree about what "verify-bearing" means: deferred stories and
    string-only acceptance contribute nothing to either.
    """
    status, failing, skipped = _last_verify(smm_dir, sprint["sprint_id"])
    if status == VERIFY_STATUS_NONE and _gather_sprint_items(sprint):
        return VERIFY_REPORT_UNVERIFIED, [], []
    return status, failing, skipped


def _last_verify(smm_dir: Path, sprint_id: str) -> tuple[str, list[dict], list[dict]]:
    """Status, failing items and SKIPPED items of this sprint's last verify.

    Returns ("none", [], []) when no verify event exists for the sprint. Callers
    that gate on the result want `verify_report` instead — `none` conflates "no
    verify-bearing acceptance" with "never verified", and only the first is
    green.

    Skipped is a third return rather than a merge into `failing` because both
    readers must be able to say which it was: an item that never ran did not
    lose. `.get("skipped", [])` also keeps an event written before this existed
    readable, which matters — the gate consumes whatever the last run emitted.
    """
    events = _common.read_events_locked(smm_dir, _AGENT_ID)
    for e in reversed(events):
        meta = e.get("metadata") or {}
        if (
            e.get("type") == EVENT_TYPE_SPRINT
            and meta.get("action") == SPRINT_ACTION_VERIFY
            and meta.get("sprint_id") == sprint_id
        ):
            return (
                meta.get("verify_status", VERIFY_STATUS_NONE),
                meta.get("failing", []),
                meta.get("skipped", []),
            )
    return VERIFY_STATUS_NONE, [], []


def unverified_items(failing: list[dict], skipped: list[dict]) -> list[str]:
    """One description per unverified item — the shared source both readers use.

    Shared so the CLI status printer and the in-process merge gate cannot drift
    into describing the same event differently. The gate built its refusal from
    `failing` alone, so a sprint red purely because items were SKIPPED refused
    with nothing after the colon: correct to refuse, useless about why, at the
    one place a human is told a merge cannot proceed.

    A LIST, not a pre-joined string: the line-per-item reader must not have to
    re-split the joined form. A declared command may itself contain the
    separator (``python3 -c "print(1, 2)"``), which would split one item into
    two bogus lines and invent an item that does not exist.
    """
    return [
        f"{_label(r)} {r.get('command', '')} (exit {r.get('returncode')})"
        for r in failing
    ] + [
        f"{_label(r)} {r.get('command', '')} (not run — batch budget)" for r in skipped
    ]


def _label(row: dict) -> str:
    """`story-007 ac2` / `story-007 ae` — the same identity the matrix prints.

    Story id alone is not enough to act on: a story declaring several verify
    commands contributes several rows, and a refusal listing the same story
    three times leaves the reader to guess which criterion is unverified. The
    matrix already distinguishes them, so the two reports agreeing costs one
    field and stops them describing the same rows differently.
    """
    idx = row.get("ac_idx")
    return f"{row.get('story', '?')} {'ae' if idx is None else f'ac{idx}'}"
