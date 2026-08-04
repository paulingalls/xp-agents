#!/usr/bin/env python3
"""What the sprint verify batch is made of, and how it is displayed.

The pure half of ``verify_acceptance --sprint``: one function turns a sprint
document into the list of items to run, the other turns the results back into
the operator's PASS/FAIL matrix. Neither shells out, reads the clock, touches
the event log, or knows an exit code — they are functions over plain data, and
that is the seam. Everything with an effect stayed in ``verify_acceptance``.

Extracted when the batch-total budget would have pushed ``verify_acceptance.py``
past this repo's file-size band, above which a module may not grow further
without shrinking back under it first. Splitting at the commit that crosses the
line is cheaper than crossing it and extracting under that constraint later.

Imports DOWN only (``_acceptance_execution``); ``verify_acceptance`` imports
these two names, never the reverse.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _acceptance_execution import extract_commands

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
            rc = r["returncode"]
            mark = "PASS" if rc == 0 else "FAIL"
            print(f"  [{mark}] {r['story']} {ac}  {r['command']}  (exit {rc})")
