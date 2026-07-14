#!/usr/bin/env python3
"""file_domain overlap detection for sprint_status.py.

Split from test_sprint_status.py at the commit that pushed it past the
500-line cap. Covers file_domains_overlap_detail (the detail-returning
helper backed by file_domain_lock.collision_report) and the bool that is
re-derived from it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)


class TestFileDomainsOverlapDetail(unittest.TestCase):
    """file_domains_overlap_detail: the detail-returning sibling of the
    overlap bool, backed by file_domain_lock.collision_report so there is
    exactly one file_domain parser.

    `collisions` is collision_report's output forwarded unchanged (path ->
    owning claims with origin). `glob_forced` is a SEPARATE signal, not
    folded into collisions: collision_report compares glob tokens as literal
    strings and would report a glob-declared frontier as disjoint, so the
    detail helper re-detects globs with the same oracle the legacy bool used
    (extract_file_domain_paths raising ValueError) and reports the
    conservative "can't prove disjoint" verdict on its own field. Callers
    need to distinguish "these two stories both claim x.py" from "a glob
    domain means disjointness can't be proven".
    """

    def _detail(self, stories, story_ids):
        import sprint_status

        return sprint_status.file_domains_overlap_detail(
            {"stories": stories}, story_ids
        )

    def test_detail_reports_collision_path_and_story_ids(self):
        detail = self._detail(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["src/a.py — owner", "src/b.py — shared"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py — caller", "src/c.py — owner"],
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertFalse(detail["glob_forced"])
        self.assertEqual(list(detail["collisions"]), ["src/b.py"])
        self.assertEqual(
            [c["story_id"] for c in detail["collisions"]["src/b.py"]],
            ["story-001", "story-002"],
        )

    def test_detail_disjoint_no_collisions(self):
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/a.py"]
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_empty_for_single_story(self):
        # Fewer than two named stories: no pair, so no claim about paths —
        # and the glob detector never runs (legacy "single glob story ->
        # False" behavior preserved).
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=["src/*"]),
                _make_story(id="story-002", status="ready", file_domain=["src/a.py"]),
            ],
            ["story-001"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_glob_forced_true(self):
        # collision_report compares "src/*" as a literal token and would say
        # disjoint. glob_forced carries the conservatism instead.
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=["src/*"]),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["docs/api.md"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertTrue(detail["glob_forced"])
        self.assertEqual(detail["collisions"], {})

    def test_detail_glob_in_non_subset_story_ignored(self):
        # The question is only about the named stories. A glob elsewhere in
        # the sprint must not force conservatism on this frontier.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/a.py"]
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(id="story-003", status="ready", file_domain=["src/*"]),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_origin_auto_included_preserved(self):
        # The sister-test globber's claims are tagged auto_included, and the
        # tag survives forwarding — the remedy differs from an authored clash.
        detail = self._detail(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["tests/test_a.py — sister test for src/a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["tests/test_a.py — authored"],
                ),
            ],
            ["story-001", "story-002"],
        )
        claims = detail["collisions"]["tests/test_a.py"]
        self.assertEqual(
            {c["story_id"]: c["origin"] for c in claims},
            {"story-001": "auto_included", "story-002": "authored"},
        )

    def test_detail_dependency_serialized_not_collision(self):
        # Sequential work sharing a file is legal — the dependency edge means
        # the two stories can never run concurrently.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py"],
                    dependencies=["story-001"],
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_terminal_story_not_collision(self):
        # A done story has merged and released its files.
        detail = self._detail(
            [
                _make_story(id="story-001", status="done", file_domain=["src/b.py"]),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_non_str_entries_ignored(self):
        # entry_to_paths raises TypeError (not ValueError) on a non-str entry,
        # a latent crash in the legacy bool. Filter before the detector runs.
        detail = self._detail(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["src/b.py", 42, None],
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertFalse(detail["glob_forced"])
        self.assertEqual(list(detail["collisions"]), ["src/b.py"])

    def test_detail_empty_file_domain_makes_no_claims(self):
        # Code-free investigation stories declare nothing: no raise, no claim.
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=[]),
                _make_story(id="story-002", status="scheduled", file_domain=[]),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_unknown_story_id_is_not_a_pair(self):
        detail = self._detail(
            [_make_story(id="story-001", status="scheduled", file_domain=["src/a.py"])],
            ["story-001", "story-404"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_is_dependency_aware(self):
        # Two stories serialized by a dependency edge may share files.
        # Customer-ratified consequence of having one file_domain parser
        # instead of two (decision 5b167f4ffdb1): the bool sibling this test
        # used to exercise is deleted, but the dependency-aware behavior
        # survives unchanged through the detail helper.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py"],
                    dependencies=["story-001"],
                ),
            ],
            ["story-001", "story-002"],
        )
        # Assert the full dict, not just collisions: the deleted bool sibling
        # was `glob_forced or collisions`, so its `is False` pinned BOTH facts.
        # Checking only collisions would let a spurious glob_forced=True slip
        # through on this literal-path input.
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_transitive_dependency_through_non_subset_story(self):
        # The edge serializing 001 and 002 runs THROUGH 003, which is NOT in
        # the subset. Scoping the dependency graph to the subset truncates the
        # transitive closure and reports a PHANTOM collision on src/b.py —
        # 002 can never run beside 001, so by the ratified definition
        # ("collision = concurrent claim only, no transitive dependency")
        # sharing the file is legal sequential work, exactly as it is for the
        # direct edge in test_detail_is_dependency_aware. The subset scopes
        # WHOSE claims are reported, never which dependencies exist.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py"],
                    dependencies=["story-003"],
                ),
                _make_story(
                    id="story-003",
                    status="scheduled",
                    file_domain=["src/c.py"],
                    dependencies=["story-001"],
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_non_subset_story_never_owns_a_collision(self):
        # The companion to the above: widening the DEPENDENCY graph to the whole
        # sprint must not widen whose CLAIMS get reported. 003 is off the subset
        # and shares src/b.py with both members, but only the named pair may
        # appear as owners — and that pair is serialized, so: no collision.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py"],
                    dependencies=["story-001"],
                ),
                _make_story(
                    id="story-003", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_called_as_sprint_frontier_will_call_it(self):
        # AC#5: sprint_frontier imports these helpers DIRECTLY from
        # sprint_status, never through sprint_store's re-export shim (there is
        # no re-export of the detail helper, by design). Exercise that path.
        from sprint_status import file_domains_overlap_detail

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="in-progress",
                    file_domain=["smm/sprint_status.py — owner"],
                ),
                _make_story(
                    id="story-002",
                    status="in-progress",
                    file_domain=["smm/sprint_status.py — consumer"],
                ),
            ]
        )
        detail = file_domains_overlap_detail(sprint, ["story-001", "story-002"])
        self.assertEqual(
            detail["collisions"],
            {
                "smm/sprint_status.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "authored"},
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
