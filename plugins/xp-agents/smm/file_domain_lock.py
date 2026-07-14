#!/usr/bin/env python3
"""Detect file_domain collisions between stories in a sprint.

`file_domain` exists to keep concurrently-running stories off each other's
files: parallel teammates work in separate worktrees, the verify-touch gate
attributes a story's proof by matching committed paths against its domain,
and a teammate reads its domain as the definition of its job. Nothing
enforced it, and the sister-test auto-include in sprint_save.py can silently
inject a file another story already claims.

A collision is therefore two claims on one path by stories that could run
CONCURRENTLY -- not merely two claims. Two stories can never run at the same
time when one transitively depends on the other, or when either has reached a
terminal status and released its files. A story building on an earlier story's
file is the normal shape of sequential work, and it is legal.

Given a loaded sprint dict this reports every colliding path, tagging each
claim as `authored` (the planner wrote it) or `auto_included` (the sister-test
globber added it). Origin matters because the remedy differs -- an authored
collision is a planner error, an auto_included one is a tool error.
"""

import sprint_schema
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
    """One story's {path: origin}, authored winning over auto_included.

    A non-list file_domain (a scalar/dict — malformed shape) yields no claims.
    collision_report defers shape validation to the schema validator (see its
    docstring), so this must not iterate a non-list: a numeric/bool file_domain
    would otherwise raise TypeError here, escaping edit_story's ValueError catch
    as an uncaught traceback. Mirrors _auto_include_sister_tests's same guard so
    both collision paths (run() and edit_story) fall through to a clean ValueError.
    """
    claims: dict[str, str] = {}
    domain = story.get("file_domain")
    if not isinstance(domain, list):
        return claims
    for entry in domain:
        if not isinstance(entry, str):
            continue
        origin = _entry_origin(entry)
        for path in triage.entry_to_paths(entry):
            if claims.get(path) == ORIGIN_AUTHORED:
                continue  # explicit beats tool; already the strongest claim
            claims[path] = origin
    return claims


def ancestors(stories: list[dict]) -> dict[str, set[str]]:
    """{story_id: every story it transitively depends on}.

    Iterated to a fixed point rather than recursed, so a malformed dependency
    cycle terminates instead of blowing the stack. In a cycle each member ends
    up an ancestor of the other, which reads as "never concurrent" -- the
    conservative answer, and the same one a topological sort could not give.

    Filters to dicts with a str `id` before indexing -- callers may pass a
    sprint's raw `stories` list (unvalidated shape), and `story["id"]`
    unfiltered would raise on a malformed entry. Mirrors `collision_report`'s
    own pre-filter so both callers share one safety net instead of each
    re-deriving it.
    """
    stories = [
        s for s in stories if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    direct: dict[str, set[str]] = {}
    for story in stories:
        deps = story.get("dependencies") or []
        direct.setdefault(story["id"], set()).update(
            d for d in deps if isinstance(d, str)
        )

    closure = {sid: set(deps) for sid, deps in direct.items()}
    changed = True
    while changed:
        changed = False
        for sid, deps in closure.items():
            grown = deps | {a for d in deps for a in closure.get(d, ())}
            if grown != deps:
                closure[sid] = grown
                changed = True
    return closure


def _concurrent(a: dict, b: dict, ancestors: dict[str, set[str]]) -> bool:
    """True when claims `a` and `b` could be worked at the same time.

    Terminal stories (done/deferred) have merged or been dropped, so they hold
    nothing. A dependency edge in either direction serializes the pair.
    """
    if a["status"] in sprint_schema.TERMINAL_STORY_STATUSES:
        return False
    if b["status"] in sprint_schema.TERMINAL_STORY_STATUSES:
        return False
    a_id, b_id = a["story_id"], b["story_id"]
    return not (b_id in ancestors.get(a_id, ()) or a_id in ancestors.get(b_id, ()))


def collision_report(data: dict) -> dict[str, list[dict]]:
    """{path: [{"story_id": str, "origin": str}, ...]} for every path claimed
    by 2+ stories that could run concurrently. Empty dict == no collisions.

    Two claims on one path are fine when the claimants are serialized by a
    dependency edge, or when either claimant is done/deferred. Duplicate
    story_ids claiming one path stay a collision -- neither depends on the
    other, so the malformed sprint is surfaced rather than excused.
    """
    stories = [
        s
        for s in data.get("stories", [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    story_ancestors = ancestors(stories)

    owners: dict[str, list[dict]] = {}
    for story in stories:
        for path, origin in _story_claims(story).items():
            owners.setdefault(path, []).append(
                {
                    "story_id": story["id"],
                    "origin": origin,
                    "status": story.get("status", ""),
                }
            )

    report: dict[str, list[dict]] = {}
    for path, claims in owners.items():
        colliding = [
            claim
            for i, claim in enumerate(claims)
            if any(
                _concurrent(claim, other, story_ancestors)
                for j, other in enumerate(claims)
                if i != j
            )
        ]
        if len(colliding) >= 2:
            colliding.sort(key=lambda c: (c["story_id"], c["origin"]))
            report[path] = [
                {"story_id": c["story_id"], "origin": c["origin"]} for c in colliding
            ]
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
