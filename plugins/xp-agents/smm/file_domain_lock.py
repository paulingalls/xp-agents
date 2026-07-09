#!/usr/bin/env python3
"""Detect file_domain collisions between stories in a sprint.

`file_domain` is documented as an exclusive-ownership invariant -- each
story owns its declared files, no overlap -- but nothing enforces it, and
the sister-test auto-include in sprint_save.py can silently inject a file
already owned by another story. This module is the pure detector: given a
loaded sprint dict, report every path claimed by 2+ stories, tagging each
claim as `authored` (planner wrote it) or `auto_included` (the sister-test
globber added it). The origin matters because the remedy differs -- an
authored collision is a planner error, an auto_included one is a tool
error. No caller is wired here; a later story wires sprint_save.run to
call this at write time.
"""

import triage

SISTER_TEST_MARKER = " — sister test for "
ORIGIN_AUTHORED = "authored"
ORIGIN_AUTO_INCLUDED = "auto_included"


def _entry_origin(entry: str) -> str:
    """Classify a raw file_domain entry before path splitting.

    Every path in a comma-joined entry inherits this one origin, so
    classification happens on the whole entry string, not per-path.
    """
    return ORIGIN_AUTO_INCLUDED if SISTER_TEST_MARKER in entry else ORIGIN_AUTHORED


def _story_claims(story: dict) -> dict[str, str]:
    """One story's {path: origin}, authored winning over auto_included."""
    claims: dict[str, str] = {}
    for entry in story.get("file_domain") or []:
        if not isinstance(entry, str):
            continue
        origin = _entry_origin(entry)
        for path in triage.entry_to_paths(entry):
            if claims.get(path) == ORIGIN_AUTHORED:
                continue  # explicit beats tool; already the strongest claim
            claims[path] = origin
    return claims


def collision_report(data: dict) -> dict[str, list[dict]]:
    """{path: [{"story_id": str, "origin": str}, ...]} for every path
    with 2+ story claims. A duplicate story_id claiming the same path
    counts as two claims (malformed sprint, still surfaced). Empty dict
    == no collisions."""
    owners: dict[str, list[dict]] = {}
    for story in data.get("stories", []):
        story_id = story.get("id")
        if not isinstance(story_id, str):
            continue
        for path, origin in _story_claims(story).items():
            owners.setdefault(path, []).append({"story_id": story_id, "origin": origin})

    report = {path: claims for path, claims in owners.items() if len(claims) >= 2}
    for claims in report.values():
        claims.sort(key=lambda c: (c["story_id"], c["origin"]))
    return dict(sorted(report.items()))


def format_collision_report(report: dict[str, list[dict]]) -> str:
    """Fail-loud multi-line message naming EVERY colliding path with
    owners + origins, plus the two remedy sentences. "" when empty."""
    if not report:
        return ""
    lines = [f"file_domain collision: {len(report)} file(s) claimed by 2+ stories:"]
    for path, owners in report.items():
        lines.append(f"  {path}")
        for owner in owners:
            origin = owner["origin"]
            suffix = " — sister-test globber" if origin == ORIGIN_AUTO_INCLUDED else ""
            lines.append(f"    {owner['story_id']} ({origin}{suffix})")
    lines.append(
        "authored collisions are a planner error: fix the offending stories' "
        "file_domain so each path has one owner."
    )
    lines.append(
        "auto_included collisions are a tool error: sister-test discovery "
        "injected a file already owned by another story."
    )
    return "\n".join(lines)
