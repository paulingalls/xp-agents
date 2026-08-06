#!/usr/bin/env python3
"""Doctrinal pin: a checkable claim routes to a test, not just a comment.

Milestone 1 measured the shipped-prose pipeline routing overflow INTO code
comments with nothing pulling back: five lines across three shipped guides
told a reader that leftover content "belongs in code comments" (or an
equivalent phrase) with no hygiene attached, and not one offered a test as a
destination. A comment is a claim with no test. This pin enforces the rule
that fixed those five lines, so it cannot regress silently:

    A checkable claim goes to a test. History goes to git. A comment carries
    only a why/constraint the code cannot express.

FOUR LEGS.

1. **Negative, corpus-wide.** Any shipped-prose line that routes something to
   a comment (destination shape: the noun phrase "code comment(s)", or
   "comment(s)" immediately arrow-routed, "comments→...") without ALSO naming
   a test as a destination on the same line is an offender. This is a SHAPE
   match, not a keyword match: `agents/xp-code-reviewer.md`'s "what-not-why
   comments" names a review target, not a routing destination, and must not
   be flagged — see `find_unqualified_comment_routing`'s docstring. Being
   corpus-wide, this leg also catches a new routing line added anywhere later,
   including in files this story does not own — provided that line uses the
   same destination shape the tree uses today. It is not a general detector
   of "routes to a comment"; see LIMITS.

2. **Vacuity guard, per file.** Each of the three files this story amends
   (`PROCESS_GUIDE.md`, `agents/xp-housekeeper.md`,
   `agents/xp-system-analyzer.md`) must still contain at least one line
   matching the comment-routing SHAPE (regardless of whether it also names a
   test — the fixed wordings still do, since they route the why/constraint
   case to a comment too). A tree-wide floor cannot see one surface empty
   out; this catches a renamed or deleted file, or a routing line deleted
   outright rather than qualified.

3. **Language-agnostic vocabulary, corpus-wide.** No shipped prose may use a
   token from `_md_helpers.CORPUS_WIDE_FORBIDDEN` — the members with no
   legitimate use in any shipped prose file, which is what makes them safe to
   ban tree-wide. This leg derives that list rather than keeping its own copy;
   the copy it used to keep drifted from the central registry, which is the
   defect story-004 closed. Deliberately NOT banning `#` — every Markdown
   heading starts with one, and a pin that noisy gets disabled, which is the
   exact failure this milestone exists to kill. Every member appears in zero
   shipped prose files today, so this leg is one legitimately-single-language
   explanation away from firing on purpose, and that is the point. This leg is
   ALSO the only check that the corpus-wide category earns its scope: a token
   with a legitimate use, mis-filed into it, fails right here, which is why the
   failure message spells out both readings.

4. **Limits, honestly stated.** See LIMITS below, modeled on
   `tests/hooks/test_no_language_leak.py`.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK.

* This pin proves a test is NAMED as a destination on the offending line. It
  never proves the routing advice is correct, that the named test exists, or
  that any comment already in the tree is true. Over-claiming coverage is
  itself the fail-silent defect this milestone targets.
* Leg 1 is per LINE. A routing clause that word-wraps across two lines in the
  source `.md` (the rendered prose is unaffected; only the raw line the
  matcher sees is) can escape both the destination match and the offender
  check.
* The "names a test" check is a heuristic tied to THIS prose's own routing
  convention — the destination article ("a test") or an arrow ("→tests"). A
  line that names a test destination in different words ("put it under test
  coverage") is still reported as an offender: leg 1 over-flags rather than
  under-flags on unfamiliar phrasing, which is the safer direction for a gate
  but is still a false positive a human has to dismiss.
* That over-flagging claim covers only the "names a test" half. BOTH matchers
  also UNDER-flag, and the reader gets no signal when they do. A future line
  routing content to "an inline comment" or "a comment in the source" matches
  no destination shape `_routing_detect.COMMENT_DEST_RE` knows, so leg 1 never
  considers it at all; and `TEST_DEST_RE` accepts any "a test" on the line, so
  a routing line mentioning a test incidentally ("belongs in code comments, not
  in a test") reads as compliant. Neither shape is in the tree today. Both are the
  deliberate price of a matcher precise enough that nobody disables it for
  noise — the same tradeoff leg 3 makes by not banning `#`.
* Leg 3 reads literal substrings only. A single-language instruction that
  spells none of `CORPUS_WIDE_FORBIDDEN`'s members (e.g. "put it in the
  module's opening string") is out of reach entirely — the same limit
  `find_prose_tool_names` in the sibling pin states for tool names.
* Leg 3 is only as wide as that category. A token with even one legitimate use
  in shipped prose belongs in `SECTION_SCOPED_FORBIDDEN` instead and so is NOT
  checked here; `.py` and `assign-pending` are two the tree relies on.

Both matchers are mutation-proved against synthetic offenders in the sibling
`test_prose_routing_pin_matchers.py`; this module owns only the assertions
over the real tree.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import rel as _rel_impl
from _pin_helpers import shipped_prose_to_scan
from _routing_detect import (
    KNOWN_ROUTING_SURFACES,
    find_comment_routing_lines,
    find_single_language_tokens,
    find_unqualified_comment_routing,
)

PLUGIN_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/
REPO_ROOT = PLUGIN_ROOT.parent.parent  # repo root, for stable rel paths


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _all_shipped_prose() -> list[Path]:
    return [p for paths in shipped_prose_to_scan(PLUGIN_ROOT).values() for p in paths]


def _scan_for_unqualified_routing() -> dict[str, list[tuple[str, int, str]]]:
    offenders: dict[str, list[tuple[str, int, str]]] = {}
    for path in _all_shipped_prose():
        surface = _rel(path)
        hits = find_unqualified_comment_routing(
            path.read_text(encoding="utf-8"), surface=surface
        )
        if hits:
            offenders[surface] = hits
    return offenders


def _scan_for_language_tokens() -> dict[str, list[tuple[str, str]]]:
    offenders: dict[str, list[tuple[str, str]]] = {}
    for path in _all_shipped_prose():
        surface = _rel(path)
        hits = find_single_language_tokens(
            path.read_text(encoding="utf-8"), surface=surface
        )
        if hits:
            offenders[surface] = hits
    return offenders


class TestNoUnqualifiedCommentRouting(unittest.TestCase):
    """Leg 1: no shipped prose line routes to a comment without also naming
    a test."""

    def test_no_shipped_prose_routes_to_a_bare_comment(self) -> None:
        offenders = _scan_for_unqualified_routing()
        self.assertEqual(
            offenders,
            {},
            "shipped prose routes a checkable claim to a comment with no "
            "test named as a destination on the same line — a comment "
            "carries only a why/constraint the code cannot express:\n"
            + "\n".join(
                f"  {surface}:{lineno}: {text}"
                for surface, hits in sorted(offenders.items())
                for _, lineno, text in hits
            ),
        )


class TestKnownRoutingFilesStillRoute(unittest.TestCase):
    """Leg 2: a renamed/deleted surface, or a deleted routing line, fails
    rather than passing vacuously."""

    def test_each_known_surface_still_yields_a_routing_line(self) -> None:
        by_rel = {_rel(p): p for p in _all_shipped_prose()}
        for surface in KNOWN_ROUTING_SURFACES:
            with self.subTest(surface=surface):
                matches = [
                    path
                    for rel_path, path in by_rel.items()
                    if rel_path.endswith(f"/{surface}")
                ]
                self.assertEqual(
                    len(matches),
                    1,
                    f"{surface} not found in the shipped prose scan (renamed, "
                    "deleted, or matched more than once)",
                )
                lines = find_comment_routing_lines(
                    matches[0].read_text(encoding="utf-8"), surface=surface
                )
                self.assertGreaterEqual(
                    len(lines),
                    1,
                    f"{surface} no longer names a comment-routing line at "
                    "all — content removed rather than qualified",
                )


class TestNoSingleLanguageCommentVocabulary(unittest.TestCase):
    """Leg 3: shipped prose names no single-language comment construct."""

    def test_no_shipped_prose_names_docstring_or_triple_quote(self) -> None:
        offenders = _scan_for_language_tokens()
        self.assertEqual(
            offenders,
            {},
            "shipped prose names a single language's comment construct — "
            "the plugin ships to Python, TypeScript, Rust, Go, Java, Ruby "
            "projects alike. TWO READINGS, and the count tells them apart: a "
            "handful of surfaces means the prose leaked; most of the tree means "
            "the token has a legitimate use and was mis-filed into "
            "CORPUS_WIDE_FORBIDDEN, where it belongs in "
            "SECTION_SCOPED_FORBIDDEN instead:\n"
            + "\n".join(
                f"  {surface}: `{token}`"
                for surface, hits in sorted(offenders.items())
                for _, token in hits
            ),
        )


if __name__ == "__main__":
    unittest.main()
