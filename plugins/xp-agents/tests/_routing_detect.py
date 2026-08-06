#!/usr/bin/env python3
"""Detection for the route-by-checkability rule: matchers plus the finders.

Two pins assert this rule over the shipped tree — `test_prose_routing_pin.py`
(a routing line names a test) and `test_prose_rule_completeness.py` (it names
all three destinations). Both need the same matchers, and the second used to
reach into the first for three underscore-private names: an import with no
declared contract that broke the moment either was renamed. Redeclaring instead
would have grown a third copy of a vocabulary that already had two.

So detection lives here, once, with public names. The pins keep only their
assertions over the real tree, and `test_prose_routing_pin_matchers.py`
exercises these functions on synthetic text.

NOT `_pin_helpers.py`: that module's docstring reserves it for discovery —
"the pin owns detection; this helper owns discovery" — and finding files is a
different job from deciding what a line says.

Named for routing rather than prose to stay distinct from milestone 2's planned
`_prose_scan.py`, which walks code for prose ratios and shares nothing with this.
"""

import re

from _md_helpers import CORPUS_WIDE_FORBIDDEN

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

# Destination shape for "routes to a comment": the noun phrase "code
# comment(s)", or "comment(s)" immediately arrow-routed ("comments→why...").
# Matching "code comment(s)" (not bare "comment(s)") is what keeps this off
# `xp-code-reviewer.md`'s "what-not-why comments" — a review target, never
# adjacent to the word "code". Case-insensitive so a sentence-initial "Code
# comments ..." bullet — ordinary in Markdown — is selected like any other.
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


def find_unqualified_comment_routing(
    text: str, surface: str
) -> list[tuple[str, int, str]]:
    """(surface, 1-based line, stripped line text) for every line whose
    comment-routing destination does not also name a test.

    Shape match, not keyword match: a line must hit `COMMENT_DEST_RE` (routes
    to a comment) before it is even considered; a line that merely contains the
    word "comment(s)" in some other sense never reaches the test-destination
    check at all.
    """
    hits: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if COMMENT_DEST_RE.search(line) and not TEST_DEST_RE.search(line):
            hits.append((surface, lineno, line.strip()))
    return hits


def find_comment_routing_lines(text: str, surface: str) -> list[tuple[str, int]]:
    """(surface, 1-based line) for every line matching the comment-routing
    destination shape, compliant or not.

    Backs the per-surface vacuity guards: the fixed wordings still route the
    why/constraint case to a comment, so this must stay non-empty on the known
    surfaces even after the offender check goes quiet on them.
    """
    return [
        (surface, lineno)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if COMMENT_DEST_RE.search(line)
    ]


def find_single_language_tokens(
    text: str, surface: str, tokens: tuple[str, ...] = CORPUS_WIDE_FORBIDDEN
) -> list[tuple[str, str]]:
    """(surface, token) for every single-language token present in *text*.

    *tokens* defaults to the corpus-wide category in `_md_helpers`. A caller
    passing its own tuple bypasses that default, so a test that supplies one
    proves nothing about the derivation — assert on the default instead.
    """
    return [(surface, token) for token in tokens if token in text]


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


def find_rule_lines(text: str, surface: str) -> list[tuple[str, int]]:
    """Alias of `find_comment_routing_lines` for the completeness pin's reader:
    the lines that state the rule are exactly the lines that route to a comment.
    """
    return find_comment_routing_lines(text, surface)
