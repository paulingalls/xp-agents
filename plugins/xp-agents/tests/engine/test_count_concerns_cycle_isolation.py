#!/usr/bin/env python3
"""`count-concerns --cycle-id --diff-paths` scopes a close gate by diff relevance.

Concern 3542ad2915df: `--cycle-id` is meant to scope a merge gate's concern
count to one close cycle, but an untagged concern matches on `--since-ts`
alone and counts anyway. story-003's auto-merge was pushed to
abort-recommended by 964426f13819 — an unrelated open lock defect recorded in
the same window with no cycle tag.

The remedy is NOT "drop untagged concerns": every concern in a real SMM is
untagged (only the close reviewers stamp `close_cycle_id`), so that would
return 0 for every gate. Instead the gate may exclude a concern only when it
is PROVABLY about code this close does not touch — it names files and none of
them intersect the close diff. Everything else still counts.

These tests pin both directions: the narrowing, and every fail-closed default
that keeps the narrowing from becoming a hole. The `--diff-paths`
empty-or-unreadable case is the one way the conjunction could fail OPEN
(vacuous "no entry intersects" against an empty set) — keep that test if the
implementation is ever refactored.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _scoped_gate_fixtures import (
    _CLI,
    _CYCLE,
    _DIFF,
    _OTHER_CYCLE,
    _OUTSIDE_DIFF,
    _WINDOW_START,
    _concern,
    _ScopedGateTestCase,
)
from conftest import run_cli, write_events


class TestUntaggedConcernsScopedByDiffRelevance(_ScopedGateTestCase):
    def test_untagged_files_miss_the_diff_is_not_counted(self) -> None:
        """The defect itself: an unrelated open concern must not abort this close."""
        write_events(self.events_file, [_concern(files=[_OUTSIDE_DIFF])])
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_untagged_files_hit_the_diff_is_counted(self) -> None:
        write_events(
            self.events_file,
            [_concern(files=["plugins/xp-agents/smm/smm_count.py"])],
        )
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_untagged_with_one_hit_among_misses_is_counted(self) -> None:
        """Relevance is ANY-intersects, not all — one touched file is enough."""
        write_events(
            self.events_file,
            [_concern(files=[_OUTSIDE_DIFF, "plugins/xp-agents/smm/smm_count.py"])],
        )
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_untagged_with_no_files_is_counted(self) -> None:
        """Nothing proves it irrelevant, so the fail-closed floor holds."""
        write_events(self.events_file, [_concern()])
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_untagged_with_empty_files_list_is_counted(self) -> None:
        """`--files '[]'` is indistinguishable from no file pin at all."""
        write_events(self.events_file, [_concern(files=[])])
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_directory_prefix_entry_counts_as_a_hit(self) -> None:
        """A concern pinned at directory granularity covers files beneath it."""
        write_events(self.events_file, [_concern(files=["plugins/xp-agents/smm"])])
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_directory_prefix_entry_outside_the_diff_is_not_counted(self) -> None:
        write_events(self.events_file, [_concern(files=["plugins/xp-agents/hooks"])])
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_slashless_entry_matches_by_basename(self) -> None:
        """f4150aa2c518's real shape: `files:['pre_tool_bash.py']` where the
        repo-relative path is plugins/xp-agents/scripts/pre_tool_bash.py.
        Exact-plus-prefix matching alone can never intersect, so such a concern
        would be excluded from EVERY close — a live fail-open."""
        write_events(self.events_file, [_concern(files=["pre_tool_bash.py"])])
        self.assertEqual(
            self._scoped(["plugins/xp-agents/scripts/pre_tool_bash.py"]), "1"
        )

    def test_slashless_entry_whose_basename_is_absent_is_not_counted(self) -> None:
        write_events(self.events_file, [_concern(files=["break_stale_lock.sh"])])
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_leading_dot_slash_is_normalized_on_both_sides(self) -> None:
        write_events(
            self.events_file,
            [_concern(files=["./plugins/xp-agents/smm/smm_count.py"])],
        )
        self.assertEqual(self._scoped(["./plugins/xp-agents/smm/smm_count.py"]), "1")

    def test_absolute_path_entry_still_counts(self) -> None:
        """An absolute entry names its file in a vocabulary `git diff
        --name-only` never emits, so exact-plus-prefix matching can never match
        it — reading that as proof of irrelevance would drop the concern from
        every scoped gate even when it names a file the close DOES touch."""
        write_events(
            self.events_file,
            [_concern(files=["/Users/dev/repo/plugins/xp-agents/smm/smm_count.py"])],
        )
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_parent_escaping_entry_still_counts(self) -> None:
        """Same class, recorded from a subdirectory instead of the repo root."""
        write_events(
            self.events_file,
            [_concern(files=["../plugins/xp-agents/smm/smm_count.py"])],
        )
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_non_string_files_entry_still_counts(self) -> None:
        """Malformed `files` proves nothing — stay on the fail-closed floor."""
        event = _concern(files=[_OUTSIDE_DIFF])
        event["files"] = [_OUTSIDE_DIFF, 17]
        write_events(self.events_file, [event])
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_blank_files_entry_still_counts(self) -> None:
        write_events(self.events_file, [_concern(files=["   "])])
        self.assertEqual(self._scoped(_DIFF), "1")


class TestTaggedConcernsUnaffected(_ScopedGateTestCase):
    def test_this_cycles_tag_counts_even_when_files_miss_the_diff(self) -> None:
        """A close reviewer's own Block is authoritative — its tag wins over
        any file heuristic."""
        write_events(
            self.events_file,
            [_concern(files=[_OUTSIDE_DIFF], cycle=_CYCLE)],
        )
        self.assertEqual(self._scoped(_DIFF), "1")

    def test_other_cycles_tag_is_not_counted(self) -> None:
        write_events(
            self.events_file,
            [
                _concern(
                    files=["plugins/xp-agents/smm/smm_count.py"], cycle=_OTHER_CYCLE
                )
            ],
        )
        self.assertEqual(self._scoped(_DIFF), "0")


class TestRuleIsOptIn(_ScopedGateTestCase):
    """`--cycle-id`'s meaning narrows ONLY when `--diff-paths` is also supplied
    and non-empty. Every other invocation counts exactly as it does today."""

    def setUp(self) -> None:
        super().setUp()
        write_events(
            self.events_file,
            [
                _concern(files=[_OUTSIDE_DIFF]),
                _concern(files=["plugins/xp-agents/smm/smm_count.py"]),
                _concern(),
            ],
        )

    def test_cycle_id_without_diff_paths_is_unchanged(self) -> None:
        self.assertEqual(
            self._count(["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START]), "3"
        )

    def test_diff_paths_without_cycle_id_is_unchanged(self) -> None:
        self.assertEqual(
            self._count(["--diff-paths", str(self._diff_file(_DIFF))]), "3"
        )

    def test_no_filters_is_unchanged(self) -> None:
        self.assertEqual(self._count([]), "3")

    def test_since_ts_still_bounds_pre_cycle_events(self) -> None:
        write_events(
            self.events_file,
            [
                _concern(files=["plugins/xp-agents/smm/smm_count.py"]),
                _concern(
                    files=["plugins/xp-agents/smm/smm_count.py"],
                    ts="2026-07-20T00:00:00+00:00",
                ),
            ],
        )
        self.assertEqual(self._scoped(_DIFF), "1")


class TestAbsentPathsAreNotProofOfIrrelevance(_ScopedGateTestCase):
    """A path missing from the working tree is the WEAKEST possible evidence of
    irrelevance, and under diff-comparison alone it was the strongest.

    The commonest reason a review names a file that is in no diff is that the
    file was never written — "no acceptance test exists for the new gate",
    recorded against the test nobody added. That path cannot appear in
    `git diff --name-only` precisely BECAUSE the work was skipped, so comparing
    against the diff alone read the absence of the work as proof the finding did
    not matter and dropped the one concern that should have stopped the merge.
    """

    def test_untagged_concern_naming_a_file_that_does_not_exist_counts(self) -> None:
        write_events(
            self.events_file,
            [_concern(files=["plugins/xp-agents/tests/hooks/test_new_gate.py"])],
        )
        self.assertEqual(self._scoped(_DIFF, materialize=False), "1")

    def test_one_absent_path_among_present_ones_counts(self) -> None:
        """All-or-nothing: the rule needs every entry readable AND present."""
        write_events(
            self.events_file,
            [_concern(files=[_OUTSIDE_DIFF, "tests/hooks/test_never_written.py"])],
        )
        (self.repo_root / _OUTSIDE_DIFF).parent.mkdir(parents=True, exist_ok=True)
        (self.repo_root / _OUTSIDE_DIFF).touch()
        self.assertEqual(self._scoped(_DIFF, materialize=False), "1")

    def test_a_present_untouched_file_is_still_excluded(self) -> None:
        """The feature itself must survive the narrowing: a file that EXISTS and
        is outside the diff is still provably other code."""
        write_events(self.events_file, [_concern(files=[_OUTSIDE_DIFF])])
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_a_present_directory_entry_outside_the_diff_is_still_excluded(self) -> None:
        write_events(self.events_file, [_concern(files=["plugins/xp-agents/hooks"])])
        (self.repo_root / "plugins/xp-agents/hooks").mkdir(parents=True)
        self.assertEqual(self._scoped(_DIFF, materialize=False), "0")

    def test_default_repo_root_is_the_cwd(self) -> None:
        """No --repo-root: paths resolve against the process cwd, which for the
        shipped gate is the repo it pipes `git diff` from. Pinned because the
        default is what every prose call site actually uses."""
        write_events(self.events_file, [_concern(files=["no/such/path/anywhere.py"])])
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--cycle-id",
                _CYCLE,
                "--since-ts",
                _WINDOW_START,
                "--diff-paths",
                str(self._diff_file(_DIFF)),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")


class TestMalformedLinesStillCount(_ScopedGateTestCase):
    def test_unparseable_line_in_window_still_counts(self) -> None:
        """An unparseable line has no readable `files`, so diff relevance can
        never narrow the fail-closed floor (unchanged behavior)."""
        self.events_file.write_text('{"id": "truncated", "ts": "2026-07-26T03:00:00+0')
        self.assertEqual(self._scoped(_DIFF), "1")


if __name__ == "__main__":
    unittest.main()
