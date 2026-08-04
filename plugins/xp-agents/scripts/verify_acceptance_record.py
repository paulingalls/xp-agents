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


def _last_verify(smm_dir: Path, sprint_id: str) -> tuple[str, list[dict], list[dict]]:
    """Status, failing items and SKIPPED items of this sprint's last verify.

    Returns ("none", [], []) when no verify event exists for the sprint — the
    close gate treats that identically to green (nothing was gated).

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


def describe_unverified(failing: list[dict], skipped: list[dict]) -> str:
    """One line naming what is unverified — for whichever reader is reporting.

    Shared so the CLI status printer and the in-process merge gate cannot drift
    into describing the same event differently. The gate built its refusal from
    `failing` alone, so a sprint red purely because items were SKIPPED refused
    with nothing after the colon: correct to refuse, useless about why, at the
    one place a human is told a merge cannot proceed.
    """
    parts = [
        f"{r.get('story', '?')} {r.get('command', '')} (exit {r.get('returncode')})"
        for r in failing
    ]
    parts += [
        f"{r.get('story', '?')} {r.get('command', '')} (not run — batch budget)"
        for r in skipped
    ]
    return ", ".join(parts)
