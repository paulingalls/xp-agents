#!/usr/bin/env python3
"""Detection for the route-by-checkability rule: matchers, finders, surfaces.

Two pins assert this rule over the shipped tree: `test_prose_rule_completeness.py`
holds every routing line to all three destinations, and
`test_prose_routing_pin.py` guards the two properties that verdict cannot see —
that each known surface still states the rule at all, and that no shipped prose
names one language's comment construct. Both read the same matchers from here,
with public names, so no module holds a second copy.

No assertion lives here: the pins own the tree-wide verdicts,
`test_prose_routing_pin_matchers.py` owns the synthetic proofs for the selector
and the token matcher, and the completeness pin keeps its own per-leg mutants
beside the rule they belong to.

NOT `_pin_helpers.py`: that module's docstring reserves it for discovery —
"this helper owns discovery" — and finding files is a different job from
deciding what a line says.

Named for routing rather than prose to stay distinct from milestone 2's planned
`_prose_scan.py`, which walks code for prose ratios and shares nothing with this.
"""

import re

from _md_helpers import CORPUS_WIDE_FORBIDDEN, SECTION_SCOPED_FORBIDDEN

# The surfaces that state the rule today. A path-segment-anchored suffix match
# on the repo-relative path, so it is immune to which glob group (root guides vs
# agents) a rename might move the file into, while still not matching a longer
# FILENAME that merely ends with one of these ("XP_PROCESS_GUIDE.md"). That
# second case would trip a per-surface assertion as a false failure rather than
# as the rename it is meant to report.
KNOWN_ROUTING_SURFACES = (
    "PROCESS_GUIDE.md",
    "agents/xp-housekeeper.md",
    "agents/xp-system-analyzer.md",
)

# Selector for "routes to a comment": the two-word phrase "code comment(s)", or
# "comment(s)" immediately arrow-routed ("comments→why..."). Case-insensitive so
# a sentence-initial "Code comments ..." bullet — ordinary in Markdown — is
# selected like any other.
#
# A PHRASE match, and it cannot tell a destination from a mention: every line
# carrying "code comment(s)" is selected, so prose that merely discusses code
# comments is held to the three-leg rule too. Requiring the two-word phrase
# rather than bare "comment(s)" is what keeps the two reviewer agents' own
# comment-hygiene lens unselected — six lines today, all of which name a comment
# as a review subject, not as somewhere content goes. Both misses are pinned as
# cases in `test_prose_rule_completeness.py`, so neither can drift unnoticed.
COMMENT_DEST_RE = re.compile(r"\bcode\s+comments?\b|\bcomments?\s*→", re.IGNORECASE)

# Destination shape for "routes to a test": the destination article ("a test")
# or an arrow immediately before it ("→tests"). Deliberately NOT "any line
# containing the word test" — `xp-system-analyzer.md`'s discriminator-test
# clause contains "test" twice as an UNRELATED noun ("discriminator test", "The
# test is") in its ORIGINAL, offending form, and a bare word-presence check
# would have been fooled by that into calling it compliant. Case-insensitive so
# a sentence-initial "A test ..." counts as the destination it plainly is,
# rather than reading as a missing test leg.
TEST_DEST_RE = re.compile(r"\ba\s+tests?\b|→\s*tests?\b", re.IGNORECASE)

# Destination shape for "routes to git". Word-anchored so `.gitignore` and
# `git_hooks` do not read as a history destination.
GIT_DEST_RE = re.compile(r"\bgit\b", re.IGNORECASE)

# The comment leg is not "a comment is allowed" but "a comment is allowed ONLY
# for what the code cannot express". Both the spelled and contracted forms ship
# today, so the matcher accepts either — the leg is the constraint, not its
# spelling. The apostrophe class covers the typographic form (escaped, since a
# literal one reads as ambiguous to the linter) as well as ASCII.
WHY_DEST_RE = re.compile("can(?:not|['\\u2019]t)\\s+express", re.IGNORECASE)

# The three legs of the whole rule, in the order a reader states them.
RULE_LEGS = (
    ("test", TEST_DEST_RE),
    ("git", GIT_DEST_RE),
    ("why", WHY_DEST_RE),
)


def find_comment_routing_lines(text: str, surface: str) -> list[tuple[str, int]]:
    """(surface, 1-based line) for every line matching the comment-routing
    destination shape, compliant or not.

    Backs the per-surface vacuity guards in BOTH pins: the fixed wordings still
    route the why/constraint case to a comment, so this must stay non-empty on
    the known surfaces even after the offender check goes quiet on them. The
    completeness pin reads it under the same reading — the lines that state the
    rule are exactly the lines that route something to a comment.
    """
    return [
        (surface, lineno)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if COMMENT_DEST_RE.search(line)
    ]


def find_single_language_tokens(text: str, surface: str) -> list[tuple[str, str]]:
    """(surface, token) for every single-language token present in *text*.

    The token list is NOT a parameter, deliberately. An injectable one lets a
    test pass a synthetic tuple, which bypasses the registry and would pass just
    as well against a hardcoded copy — proving only that the parameter exists.
    Reading `CORPUS_WIDE_FORBIDDEN` here makes the derivation the only thing a
    caller can exercise.
    """
    return [(surface, token) for token in CORPUS_WIDE_FORBIDDEN if token in text]


def find_section_scoped_tokens(text: str, surface: str) -> list[tuple[str, str]]:
    """(surface, token) for every section-scoped token present in *text*.

    Mirror of `find_single_language_tokens`, non-injectable for the same reason.
    Its caller asks the opposite question: not "did a banned token leak" but
    "does this token still have the legitimate use that justified filing it
    section-scoped".
    """
    return [(surface, token) for token in SECTION_SCOPED_FORBIDDEN if token in text]


def zero_use_members(members: tuple[str, ...], texts: list[str]) -> list[str]:
    """Members of *members* occurring in none of *texts*."""
    return [member for member in members if not any(member in text for text in texts)]


def find_incomplete_rule_lines(text: str, surface: str) -> list[tuple[str, int, str]]:
    """(surface, 1-based line, missing legs) for every routing line that names
    fewer than all three destinations."""
    hits: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not COMMENT_DEST_RE.search(line):
            continue
        missing = [name for name, matcher in RULE_LEGS if not matcher.search(line)]
        if missing:
            hits.append((surface, lineno, ",".join(missing)))
    return hits
