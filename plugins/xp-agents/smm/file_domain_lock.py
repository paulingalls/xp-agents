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

A GLOB entry claims every path it matches, so a story declaring
`skills/*/SKILL.md` collides with one declaring `skills/xp-assign/SKILL.md`.
Matching is against paths some story DECLARED, never against the filesystem:
`triage.extract_file_domain_paths` expands a pattern over what exists on disk,
so a pattern whose only match is a file this sprint has yet to create would slip
the gate -- the opposite of what a gate is for. Such a claim is tagged with the
`pattern` that produced it, because "each path needs one owner" is not
actionable advice for a claimant that never named the path.

Glob-vs-glob overlap is deliberately NOT detected: two different patterns that
could match one file are not compared (debt 40626375ff25). Two IDENTICAL pattern
strings still collide, on the same string-equality path as any literal.
"""

import re

import glob_translator
import sprint_schema
import triage

SISTER_TEST_MARKER = " — sister test for "
ORIGIN_AUTHORED = "authored"
ORIGIN_AUTO_INCLUDED = "auto_included"

# A file_domain entry containing any of these is a PATTERN; anything else is a
# literal path. Kept in step with glob_translator.glob_to_regex, the single
# translator this module reuses -- those are exactly the characters it treats as
# metacharacters.
_GLOB_META_RE = re.compile(r"[*?\[]")


def _is_pattern(entry: str) -> bool:
    return _GLOB_META_RE.search(entry) is not None


def _claim_rank(origin: str, pattern: str | None) -> tuple[bool, bool]:
    """Which of ONE story's several claims on one path gets reported.

    Origin dominates -- that is the pre-existing "explicit beats tool" rule,
    unchanged. Directness only breaks the tie, because a report naming the entry
    the planner actually wrote is more actionable than one naming a pattern that
    happens to cover it.
    """
    return (origin == ORIGIN_AUTHORED, pattern is None)


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


def _concurrent(a: dict, b: dict, story_ancestors: dict[str, set[str]]) -> bool:
    """True when claims `a` and `b` could be worked at the same time.

    Terminal stories (done/deferred) have merged or been dropped, so they hold
    nothing. A dependency edge in either direction serializes the pair --
    `story_ancestors` is transitive, so an indirect edge serializes it too.
    """
    if a["status"] in sprint_schema.TERMINAL_STORY_STATUSES:
        return False
    if b["status"] in sprint_schema.TERMINAL_STORY_STATUSES:
        return False
    a_id, b_id = a["story_id"], b["story_id"]
    return not (
        b_id in story_ancestors.get(a_id, ()) or a_id in story_ancestors.get(b_id, ())
    )


def _resolved_claims(
    story: dict, claims: dict[str, str], literals: set[str]
) -> dict[str, dict]:
    """ONE claim per path for a single story, patterns expanded over `literals`.

    Exactly one claim per (story, path) is the load-bearing part. `_story_claims`
    used to guarantee it structurally -- a `dict` keyed by path cannot hold two
    entries for one path -- and pattern expansion destroys that guarantee: a
    story may legitimately declare a domain-wide pattern AND one file inside it,
    and two patterns may both match one path. Since `_concurrent(a, b)` is True
    for a story against ITSELF (a story is not its own ancestor), an
    un-collapsed second claim would report the story as colliding with itself.
    `_claim_rank` picks which of the several survives.

    A pattern also claims its own literal spelling, so two stories declaring the
    same pattern string still collide -- the pre-glob behavior, preserved.
    """
    resolved: dict[str, dict] = {}
    matchers: dict[str, re.Pattern[str]] = {}
    for entry, origin in claims.items():
        targets: list[tuple[str, str | None]] = [(entry, None)]
        if _is_pattern(entry):
            matcher = matchers.setdefault(
                entry, re.compile(glob_translator.glob_to_regex(entry))
            )
            targets += [(lit, entry) for lit in literals if matcher.fullmatch(lit)]
        for path, pattern in targets:
            prior = resolved.get(path)
            if prior is not None and _claim_rank(
                prior["origin"], prior["pattern"]
            ) >= _claim_rank(origin, pattern):
                continue
            resolved[path] = {
                "story_id": story["id"],
                "origin": origin,
                "status": story.get("status", ""),
                "pattern": pattern,
            }
    return resolved


def _public_claim(claim: dict) -> dict:
    """A report claim: internal `status` dropped, `pattern` only when there is
    one, so a literal-only collision keeps the exact pre-glob shape."""
    public = {"story_id": claim["story_id"], "origin": claim["origin"]}
    if claim.get("pattern"):
        public["pattern"] = claim["pattern"]
    return public


def collision_report(
    data: dict, *, scope: set[str] | None = None
) -> dict[str, list[dict]]:
    """{path: [{"story_id", "origin", "pattern"?}, ...]} for every path claimed
    by 2+ stories that could run concurrently. Empty dict == no collisions.
    `pattern` is present only on a claim a GLOB entry produced, and names that
    glob.

    Two claims on one path are fine when the claimants are serialized by a
    dependency edge, or when either claimant is done/deferred. Duplicate
    story_ids claiming one path stay a collision -- neither depends on the
    other, so the malformed sprint is surfaced rather than excused.

    `scope` restricts WHOSE claims are reported (None = every story). It must
    never restrict which DEPENDENCIES exist: serialization is transitive, so an
    edge between two scoped stories can run through an unscoped one. Pass the
    whole sprint as `data` and narrow with `scope` -- pre-filtering `data` to
    the scoped stories instead would truncate the closure and report a phantom
    collision between a pair that is in fact strictly sequential.

    Patterns expand over the SCOPED stories' literal paths only. Where one
    claimant is a literal that narrowing is free -- the literal's own story must
    be scoped to be reported at all. It is NOT free where BOTH claimants are
    patterns matching an out-of-scope story's literal: widening would surface
    that pair. That is glob-vs-glob overlap (debt 40626375ff25), undetected here
    by design, so the narrowing costs nothing this function already promises --
    but it is a narrowing, not a no-op, and closing that debt must revisit it.
    """
    stories = [
        s
        for s in data.get("stories", [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    story_ancestors = ancestors(stories)
    scoped = [s for s in stories if scope is None or s["id"] in scope]

    per_story = [(s, _story_claims(s)) for s in scoped]
    literals = {
        path for _, claims in per_story for path in claims if not _is_pattern(path)
    }

    owners: dict[str, list[dict]] = {}
    for story, claims in per_story:
        for path, claim in _resolved_claims(story, claims, literals).items():
            owners.setdefault(path, []).append(claim)

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
            colliding.sort(
                key=lambda c: (c["story_id"], c["origin"], c["pattern"] or "")
            )
            report[path] = [_public_claim(c) for c in colliding]
    return dict(sorted(report.items()))


def format_collision_report(report: dict[str, list[dict]]) -> str:
    """Fail-loud multi-line message naming EVERY colliding path with
    owners + origins, plus the remedy sentences. "" when empty.

    A pattern-derived claim names its pattern next to the path it matched, and
    adds a third remedy sentence: "each path has one owner" cannot be acted on
    by a claimant whose file_domain never mentions the path.
    """
    if not report:
        return ""
    lines = [f"file_domain collision: {len(report)} file(s) claimed by 2+ stories:"]
    any_pattern = False
    for path, owners in report.items():
        lines.append(f"  {path}")
        for owner in owners:
            origin = owner["origin"]
            suffix = " — sister-test globber" if origin == ORIGIN_AUTO_INCLUDED else ""
            pattern = owner.get("pattern")
            if pattern:
                any_pattern = True
                suffix += f" — via pattern {pattern}"
            lines.append(f"    {owner['story_id']} ({origin}{suffix})")
    lines.append(
        "authored collisions are a planner error: fix the offending stories' "
        "file_domain so each path has one owner."
    )
    lines.append(
        "auto_included collisions are a tool error: sister-test discovery "
        "injected a file already owned by another story."
    )
    if any_pattern:
        lines.append(
            "a pattern claims every declared path it matches: narrow the pattern "
            "to exclude that path, or drop the explicit entry — the pattern's "
            "owner never named the path, so it cannot 'fix the path'."
        )
    return "\n".join(lines)
