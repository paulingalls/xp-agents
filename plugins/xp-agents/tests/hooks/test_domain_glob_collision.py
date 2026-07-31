#!/usr/bin/env python3
"""Pin: a glob claim collides with every explicit path it matches (story-010 AC5).

`file_domain_lock` compared glob entries as literal strings, so a story declaring
`skills/*/SKILL.md` and one declaring `skills/xp-assign/SKILL.md` read as
disjoint domains — and two teammates were cleared to edit one file.

Split out of `test_spawn_determinism.py` at 651 lines. It stays in this directory
rather than moving beside `tests/engine/test_file_domain_lock.py`: the collision
lock is what decides whether two teammates may run at once, so it belongs to the
spawn-determinism contract even though the code it exercises does not spawn.

Glob-vs-glob overlap (two DIFFERENT patterns that could match one file) stays
undetected by design — debt 40626375ff25. Identical pattern strings still
collide, which `test_identical_patterns_still_collide` holds.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import file_domain_lock
from conftest import make_sprint_dict, make_story_dict


class TestGlobAwareCollisionDetection(unittest.TestCase):
    """A pattern claim collides with every explicit path it matches (AC5)."""

    def test_pattern_collides_with_an_explicit_path_it_matches(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001", file_domain=["skills/*/SKILL.md — every skill"]
                ),
                make_story_dict(
                    id="story-002",
                    file_domain=["skills/xp-assign/SKILL.md — the assign skill"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertIn("skills/xp-assign/SKILL.md", report)
        claims = report["skills/xp-assign/SKILL.md"]
        self.assertEqual([c["story_id"] for c in claims], ["story-001", "story-002"])
        self.assertEqual(claims[0].get("pattern"), "skills/*/SKILL.md")
        # The explicit claimant is direct — no pattern to name.
        self.assertIsNone(claims[1].get("pattern"))

    def test_report_names_both_the_pattern_and_the_matched_path(self):
        report = {
            "skills/xp-assign/SKILL.md": [
                {
                    "story_id": "story-001",
                    "origin": "authored",
                    "pattern": "skills/*/SKILL.md",
                },
                {"story_id": "story-002", "origin": "authored"},
            ]
        }
        message = file_domain_lock.format_collision_report(report)
        self.assertIn("skills/xp-assign/SKILL.md", message)
        self.assertIn("skills/*/SKILL.md", message)
        self.assertIn("story-001", message)
        self.assertIn("story-002", message)

    def test_report_tells_a_pattern_claimant_what_to_do(self):
        """ "fix the file_domain so each path has one owner" is unactionable when
        one claimant never named the path: the remedy is to narrow the pattern
        or drop the explicit entry."""
        report = {
            "a/b.py": [
                {"story_id": "story-001", "origin": "authored", "pattern": "a/*.py"},
                {"story_id": "story-002", "origin": "authored"},
            ]
        }
        message = file_domain_lock.format_collision_report(report)
        self.assertRegex(message, r"(?i)narrow the pattern")

    def test_pattern_matching_no_file_on_disk_still_collides(self):
        """The gate compares DECLARED entries, never the filesystem — a pattern
        whose only match does not exist yet must not slip through (that is why
        triage.extract_file_domain_paths is not the oracle here)."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001", file_domain=["nonexistent/**/*.rs — future crate"]
                ),
                make_story_dict(
                    id="story-002", file_domain=["nonexistent/deep/lib.rs — the file"]
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertIn("nonexistent/deep/lib.rs", report)

    def test_recursive_pattern_matches_a_nested_explicit_path(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["src/**/*.ts — all TS"]),
                make_story_dict(
                    id="story-002", file_domain=["src/a/b/c.ts — one file"]
                ),
            ]
        )
        self.assertIn("src/a/b/c.ts", file_domain_lock.collision_report(data))

    def test_star_does_not_cross_a_slash(self):
        """`*` is one segment, so `skills/*.md` must NOT claim a nested file —
        otherwise the gate over-reports and every glob domain blocks parallel
        work."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001", file_domain=["skills/*.md — top level"]
                ),
                make_story_dict(
                    id="story-002", file_domain=["skills/xp-assign/SKILL.md — nested"]
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_non_matching_pattern_is_not_a_collision(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["scripts/*.py — scripts"]),
                make_story_dict(id="story-002", file_domain=["smm/triage.py — triage"]),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_identical_patterns_still_collide(self):
        """Regression guard on the pre-existing literal-string comparison: the
        glob-vs-glob debt is "different patterns", never "the same pattern
        twice"."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(id="story-001", file_domain=["src/*.py — glob"]),
                make_story_dict(id="story-002", file_domain=["src/*.py — glob too"]),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            [c["story_id"] for c in report["src/*.py"]], ["story-001", "story-002"]
        )

    def test_dependency_edge_still_serializes_a_pattern_collision(self):
        """Glob awareness widens WHICH claims meet; it must not touch the
        concurrency rule that excuses two claims on one path."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001", file_domain=["skills/*/SKILL.md — all"]
                ),
                make_story_dict(
                    id="story-002",
                    file_domain=["skills/xp-assign/SKILL.md — one"],
                    dependencies=["story-001"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})


class TestStoryNeverCollidesWithItself(unittest.TestCase):
    """The structural guarantee `dict[path, origin]` used to give for free.

    One story may legitimately declare a pattern AND an explicit path the
    pattern matches (a domain plus the one file it calls out). Pattern matching
    makes that TWO claims on one path from one story, and `_concurrent(a, b)`
    is True for a story against itself — a story is not its own ancestor. So the
    collapse has to be deliberate.
    """

    def test_pattern_plus_matching_explicit_path_in_one_story(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=[
                        "skills/*/SKILL.md — every skill",
                        "skills/xp-assign/SKILL.md — this one in particular",
                    ],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_self_claim_collapses_to_the_direct_entry(self):
        """When another story DOES collide, the self-overlapping story appears
        exactly once — and as the direct claimant, since it named the path."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=[
                        "skills/*/SKILL.md — every skill",
                        "skills/xp-assign/SKILL.md — this one",
                    ],
                ),
                make_story_dict(
                    id="story-002", file_domain=["skills/xp-assign/SKILL.md — mine"]
                ),
            ]
        )
        claims = file_domain_lock.collision_report(data)["skills/xp-assign/SKILL.md"]
        self.assertEqual([c["story_id"] for c in claims], ["story-001", "story-002"])
        self.assertIsNone(claims[0].get("pattern"))

    def test_two_patterns_in_one_story_matching_one_declared_path(self):
        """Both patterns match story-002's path; story-001 must still contribute
        ONE claim, not one per pattern."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    file_domain=["src/*.py — by star", "src/**/*.py — by recursion"],
                ),
                make_story_dict(id="story-002", file_domain=["src/a.py — the file"]),
            ]
        )
        claims = file_domain_lock.collision_report(data)["src/a.py"]
        self.assertEqual([c["story_id"] for c in claims], ["story-001", "story-002"])


class TestBracketedPathIsNotAGlob(unittest.TestCase):
    """A bracketed SEGMENT is a real filename in several ecosystems (Next.js /
    SvelteKit route params). Reading it as a character class made a literal
    file claim unrelated paths and then offered "narrow the pattern" as the
    remedy for something that is not a pattern."""

    def test_route_param_path_does_not_claim_a_matching_literal(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="in-progress",
                    file_domain=["app/[id]/page.tsx — one"],
                ),
                make_story_dict(
                    id="story-002",
                    status="in-progress",
                    file_domain=["app/i/page.tsx — two"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})

    def test_identical_route_param_paths_still_collide_as_literals(self):
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="in-progress",
                    file_domain=["app/[id]/page.tsx — one"],
                ),
                make_story_dict(
                    id="story-002",
                    status="in-progress",
                    file_domain=["app/[id]/page.tsx — two"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            sorted(c["story_id"] for c in report["app/[id]/page.tsx"]),
            ["story-001", "story-002"],
        )
        # ...and as a LITERAL, so no unactionable "narrow the pattern" remedy.
        self.assertNotIn("pattern", report["app/[id]/page.tsx"][0])

    def test_a_wildcard_beside_a_class_still_expands(self):
        """The narrowing is about classification, not about dropping bracket
        support: a real wildcard still makes the entry a pattern, and the
        translator still honours the class inside it."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="in-progress",
                    file_domain=["src/[ab]*.py — one"],
                ),
                make_story_dict(
                    id="story-002",
                    status="in-progress",
                    file_domain=["src/alpha.py — two"],
                ),
            ]
        )
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            sorted(c["story_id"] for c in report["src/alpha.py"]),
            ["story-001", "story-002"],
        )

    def test_an_uncompilable_class_does_not_escape_as_a_regex_error(self):
        """`[]` is an unterminated character set. An inline re.compile here
        turned one malformed file_domain entry into a traceback out of a
        read-only report."""
        data = make_sprint_dict(
            stories=[
                make_story_dict(
                    id="story-001",
                    status="in-progress",
                    file_domain=["src/[]*.py — one"],
                ),
                make_story_dict(
                    id="story-002",
                    status="in-progress",
                    file_domain=["src/alpha.py — two"],
                ),
            ]
        )
        self.assertEqual(file_domain_lock.collision_report(data), {})


if __name__ == "__main__":
    unittest.main()
