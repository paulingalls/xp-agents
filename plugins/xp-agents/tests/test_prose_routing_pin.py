#!/usr/bin/env python3
"""Doctrinal pin: the properties a corpus-wide routing verdict cannot see.

Milestone 1 measured the shipped-prose pipeline routing overflow INTO code
comments with nothing pulling back: five lines across three shipped guides
told a reader that leftover content "belongs in code comments" (or an
equivalent phrase) with no hygiene attached, and not one offered a test as a
destination. A comment is a claim with no test. The rule that fixed those five
lines is:

    A checkable claim goes to a test. History goes to git. A comment carries
    only a why/constraint the code cannot express.

`test_prose_rule_completeness.py` holds every shipped routing line to all three
destinations, which subsumes any weaker "names a test" check over the same
corpus. This module owns the guards that assertion cannot make.

THREE LEGS.

1. **Vacuity guard, per file.** Each of the three files this story amends
   (`PROCESS_GUIDE.md`, `agents/xp-housekeeper.md`,
   `agents/xp-system-analyzer.md`) must still contain at least one line
   matching the comment-routing selector. A tree-wide floor goes green when the
   last routing line is deleted or a file is renamed away, and reports nothing;
   this catches both.

2. **Language-agnostic vocabulary, corpus-wide.** No shipped prose may use a
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

3. **Occupancy, corpus-wide, the reverse of leg 2 — story-007.** Leg 2 checks
   that a corpus-wide member has no legitimate use anywhere; nothing checked
   the opposite direction, so a token with NO legitimate use ANYWHERE, filed
   into `_md_helpers.SECTION_SCOPED_FORBIDDEN` instead, was examined only
   inside the selected sections that call `assert_project_agnostic` — a handful
   of shipped prose files, not all of them. This leg closes that: every
   `SECTION_SCOPED_FORBIDDEN` member not in `_md_helpers.OCCUPANCY_EXEMPT` must
   occur in at least one of the same shipped prose files leg 2 scans. "Tree-
   wide" here means that PROSE corpus, not shipped code — against
   shipped `.py` files the occupancy counts invert completely (`def ` alone
   hits hundreds of files), so a reader who checks the wrong corpus will see
   this leg as nonsense. `OCCUPANCY_EXEMPT` carves out the members this leg
   cannot safely judge either way: `def `/`class `/`function ` read as used or
   unused depending on whether the hit is the declaration keyword or ordinary
   English.

LIMITS — READ THIS BEFORE TRUSTING THE GREEN CHECK.

* Leg 1 proves a routing line is PRESENT on each known surface. It never
  proves the advice on that line is correct, or that any comment already in
  the tree is true. Over-claiming coverage is itself the fail-silent defect
  this milestone targets. Whether a present line states the WHOLE rule is the
  sibling pin's verdict, not this one's; whether a test a comment NAMES still
  exists is `test_prose_pointer_pin`'s.
* Leg 1 is per LINE and reads only `_routing_detect.COMMENT_DEST_RE`, so a
  routing clause that word-wraps across two lines in the source `.md`, or one
  phrased as "an inline comment", counts for nothing here — a surface whose
  only routing line takes either form reads as empty and fails leg 1 as a
  false positive. Neither shape is in the tree today; both misses are pinned
  as cases in the sibling completeness pin.
* Leg 2 matches on genuine occurrence (`_vocab_detect.token_occurs`), anchored
  to a member's own alphanumeric edges — not a bare substring. A single-
  language instruction that spells none of `CORPUS_WIDE_FORBIDDEN`'s members
  (e.g. "put it in the module's opening string") is still out of reach
  entirely — the same limit `find_prose_tool_names` in the sibling pin states
  for tool names.
* Leg 2 is only as wide as that category. A token with even one legitimate use
  in shipped prose belongs in `SECTION_SCOPED_FORBIDDEN` instead and so is NOT
  checked here; `.py` and `assign-pending` are two the tree relies on.
* Leg 3 checks several members whose only remaining shipped-prose use is a
  single occurrence: `.go`, `ACCEPT_IN_FLIGHT`, `simplify_done`,
  `assign-pending`. One prose edit that removes that one use reddens this leg
  — a designed tripwire pointing at the token's sole legitimizing use, not a
  flaky test. When leg 3 fires on one of these, read the failure message's two
  readings before assuming the fix is deletion.

Every matcher is mutation-proved against synthetic input in the sibling
`test_prose_routing_pin_matchers.py`; this module owns only the assertions
over the real tree.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _md_helpers import OCCUPANCY_EXEMPT, SECTION_SCOPED_FORBIDDEN
from _pin_helpers import rel as _rel_impl
from _pin_helpers import shipped_prose_to_scan
from _routing_detect import (
    KNOWN_ROUTING_SURFACES,
    KNOWN_VERIFY_CLAIM_SURFACES,
    find_comment_routing_lines,
    find_single_language_tokens,
    find_verify_claim_lines,
    zero_use_members,
)

PLUGIN_ROOT = Path(__file__).parent.parent  # plugins/xp-agents/
REPO_ROOT = PLUGIN_ROOT.parent.parent  # repo root, for stable rel paths


def _rel(path: Path) -> str:
    return _rel_impl(path, REPO_ROOT)


def _all_shipped_prose() -> list[Path]:
    return [p for paths in shipped_prose_to_scan(PLUGIN_ROOT).values() for p in paths]


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


class TestKnownRoutingFilesStillRoute(unittest.TestCase):
    """Leg 1: a renamed/deleted surface, or a deleted routing line, fails
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


class TestKnownSurfacesStateTheVerifyClaimRule(unittest.TestCase):
    """Leg 4: routing tells a reader where content belongs; it says nothing
    about content already in the wrong shape. The rule for that — a claim the
    code contradicts is narrowed to what is true, not deleted — shipped to the
    two reviewer agents and nowhere else, so a reader of the guide met the
    routing half of the doctrine and not this one. `tests/smm/test_seed.py`
    holds the fourth surface, the seeded wisdom, which is generated rather than
    a prose file."""

    def test_each_surface_still_states_it(self) -> None:
        by_rel = {_rel(p): p for p in _all_shipped_prose()}
        for surface in KNOWN_VERIFY_CLAIM_SURFACES:
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
                lines = find_verify_claim_lines(
                    matches[0].read_text(encoding="utf-8"), surface=surface
                )
                self.assertGreaterEqual(
                    len(lines),
                    1,
                    f"{surface} no longer names the contradicted-claim case "
                    "with narrowing as its fix",
                )


class TestNoSingleLanguageCommentVocabulary(unittest.TestCase):
    """Leg 2: shipped prose names no single-language comment construct."""

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


class TestSectionScopedMembersStillEarnTheirScope(unittest.TestCase):
    """Leg 3: the reverse of leg 2. A `SECTION_SCOPED_FORBIDDEN` member with
    zero uses across every shipped prose file has no legitimate use to
    protect and was mis-filed — it belongs in `CORPUS_WIDE_FORBIDDEN`."""

    def test_every_non_exempt_member_occurs_somewhere_in_shipped_prose(self) -> None:
        texts = [p.read_text(encoding="utf-8") for p in _all_shipped_prose()]
        candidates = tuple(
            token for token in SECTION_SCOPED_FORBIDDEN if token not in OCCUPANCY_EXEMPT
        )
        unused = zero_use_members(candidates, texts)
        self.assertEqual(
            unused,
            [],
            f"SECTION_SCOPED_FORBIDDEN member(s) with zero uses across all "
            f"{len(texts)} shipped prose files — TWO READINGS: either the token has no "
            "legitimate use anywhere and belongs promoted to "
            "CORPUS_WIDE_FORBIDDEN, or its one legitimate use was just edited "
            "away and restoring it is the fix:\n"
            + "\n".join(f"  {token!r}" for token in unused),
        )


if __name__ == "__main__":
    unittest.main()
