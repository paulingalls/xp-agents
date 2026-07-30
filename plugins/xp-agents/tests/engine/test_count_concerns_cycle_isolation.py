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

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from conftest import _SMMTestCase, make_event, run_cli, write_events
from event_schema import EVENT_TYPE_CONCERN, METADATA_KEY_CLOSE_CYCLE_ID

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"
_APPEND_IMPL = Path(__file__).parent.parent.parent / "smm" / "_append_impl.py"

# This close cycle vs. a concurrent teammate's close cycle.
_CYCLE = "aaaa11112222"
_OTHER_CYCLE = "bbbb33334444"

# The close window: WINDOW_START is the preload's CLOSE_START_TS, IN_WINDOW is
# any event recorded after it (so --since-ts alone can never exclude it — the
# whole point of the concern being fixed).
_WINDOW_START = "2026-07-26T00:00:00+00:00"
_IN_WINDOW = "2026-07-26T02:36:49+00:00"

# This story's domain, standing in for a close diff.
_DIFF = [
    "plugins/xp-agents/smm/smm_count.py",
    "plugins/xp-agents/tests/engine/test_count_concerns_cycle_isolation.py",
]
# A file outside it — 964426f13819's real `files` entry. Used as a STRING
# only: a sibling story is deleting this path, and this fixture must not care.
_OUTSIDE_DIFF = "plugins/xp-agents/smm/break_stale_lock.sh"


def _concern(
    severity: str = "high",
    *,
    files: list[str] | None = None,
    cycle: str | None = None,
    ts: str = _IN_WINDOW,
) -> dict:
    """Concern event inside the close window. `files=None` omits the key
    entirely (the shape a concern raised without `--files` has)."""
    metadata = {METADATA_KEY_CLOSE_CYCLE_ID: cycle} if cycle else {}
    event = make_event(EVENT_TYPE_CONCERN, severity=severity, ts=ts, metadata=metadata)
    if files is not None:
        event["files"] = files
    return event


class _ScopedGateTestCase(_SMMTestCase):
    """Shared plumbing: write concerns, run the gate query, read the count.

    `--repo-root` points at a synthetic working tree rather than this repo, so
    no fixture depends on a real file surviving a sibling story's deletions.
    `_scoped` MATERIALIZES every path the written concerns record, because
    outside-the-diff is proof of irrelevance only for a file that is there and
    simply untouched — a path that does not exist keeps its concern counted
    (`TestAbsentPathsAreNotProofOfIrrelevance` pins the other direction).
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo_root = self.smm_dir / "fake-repo"
        self.repo_root.mkdir()

    def _count(self, extra_args: list[str], stdin_data: str | None = None) -> str:
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--repo-root",
                str(self.repo_root),
                *extra_args,
            ],
            self.smm_dir,
            stdin_data=stdin_data,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _diff_file(self, paths: list[str]) -> Path:
        """Write a `git diff --name-only` capture next to the temp SMM."""
        path = self.smm_dir / "close-diff.txt"
        path.write_text("".join(f"{p}\n" for p in paths))
        return path

    def _materialize_recorded_files(self) -> None:
        """Create every repo-relative path the written concerns name."""
        for line in self.events_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # deliberately-corrupt fixtures record no files
            for entry in event.get("files") or []:
                if not isinstance(entry, str) or not entry.strip():
                    continue
                path = self.repo_root / entry.strip()
                if ".." in path.parts or entry.strip().startswith(("/", "~")):
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

    def _scoped(self, paths: list[str], *, materialize: bool = True) -> str:
        """The real gate invocation: cycle + window + close diff."""
        if materialize:
            self._materialize_recorded_files()
        return self._count(
            [
                "--cycle-id",
                _CYCLE,
                "--since-ts",
                _WINDOW_START,
                "--diff-paths",
                str(self._diff_file(paths)),
            ]
        )


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


class TestDiffPathsFailsClosed(_ScopedGateTestCase):
    """`--diff-paths` that parses to an empty set must behave EXACTLY as if it
    were never supplied. Without this the rule is fail-OPEN: "no entry
    intersects" is vacuously true against an empty set, so every untagged
    concern with `files` drops and the gate returns ~0.

    Every branch here is reachable in the shipped prose: story-close's preload
    emits STORY_BASE_UNRESOLVED=true when get-base refuses, a failed `git diff`
    inside `$(...)` delivers empty stdin silently (no `pipefail` in the prose),
    and an empty commit range prints nothing.
    """

    def setUp(self) -> None:
        super().setUp()
        write_events(self.events_file, [_concern(files=[_OUTSIDE_DIFF])])

    def _empty_diff_paths_args(self, spec: str) -> list[str]:
        return ["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START, "--diff-paths", spec]

    def test_empty_file_counts_everything(self) -> None:
        empty = self.smm_dir / "empty-diff.txt"
        empty.write_text("")
        self.assertEqual(self._count(self._empty_diff_paths_args(str(empty))), "1")

    def test_whitespace_only_file_counts_everything(self) -> None:
        blank = self.smm_dir / "blank-diff.txt"
        blank.write_text("\n  \n\n")
        self.assertEqual(self._count(self._empty_diff_paths_args(str(blank))), "1")

    def test_missing_file_counts_everything(self) -> None:
        missing = self.smm_dir / "no-such-diff.txt"
        self.assertEqual(self._count(self._empty_diff_paths_args(str(missing))), "1")

    def test_directory_instead_of_file_counts_everything(self) -> None:
        self.assertEqual(
            self._count(self._empty_diff_paths_args(str(self.smm_dir))), "1"
        )

    def test_undecodable_file_counts_everything(self) -> None:
        """A non-UTF-8 filename in the path list must degrade to counting, not
        raise — the gate captures stdout in `$(...)`, so a traceback becomes an
        empty count the calling `[ "$N" -gt 0 ]` test cannot read."""
        binary = self.smm_dir / "binary-diff.txt"
        binary.write_bytes(b"plugins/xp-agents/caf\xe9.py\n")
        self.assertEqual(self._count(self._empty_diff_paths_args(str(binary))), "1")

    def test_empty_stdin_counts_everything(self) -> None:
        self.assertEqual(
            self._count(self._empty_diff_paths_args("-"), stdin_data=""), "1"
        )

    def test_empty_diff_paths_notes_the_degradation_on_stderr(self) -> None:
        """Silently counting everything looks like the rule fired and found a
        hit. The operator needs to see that the diff never arrived."""
        empty = self.smm_dir / "empty-diff.txt"
        empty.write_text("")
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                *self._empty_diff_paths_args(str(empty)),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--diff-paths", result.stderr)


class TestDiffPathsFromStdin(_ScopedGateTestCase):
    """A close diff can be long, so `-` reads it from stdin."""

    def test_stdin_paths_exclude_an_irrelevant_concern(self) -> None:
        write_events(self.events_file, [_concern(files=[_OUTSIDE_DIFF])])
        self._materialize_recorded_files()
        args = ["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START, "--diff-paths", "-"]
        self.assertEqual(
            self._count(args, stdin_data="".join(f"{p}\n" for p in _DIFF)), "0"
        )

    def test_stdin_paths_keep_a_relevant_concern(self) -> None:
        write_events(
            self.events_file,
            [_concern(files=["plugins/xp-agents/smm/smm_count.py"])],
        )
        args = ["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START, "--diff-paths", "-"]
        self.assertEqual(
            self._count(args, stdin_data="".join(f"{p}\n" for p in _DIFF)), "1"
        )

    def test_stdin_nul_separated_paths_keep_a_relevant_concern(self) -> None:
        """`git diff --name-only -z` NUL-terminates instead of newline-terminating
        (story-003) — the reader must split on NUL too. Materializing the file is
        load-bearing here: without it, `_names_existing_code` already keeps the
        concern counted regardless of diff parsing, and the test would pass even
        against the un-fixed reader."""
        write_events(
            self.events_file,
            [_concern(files=["plugins/xp-agents/smm/smm_count.py"])],
        )
        self._materialize_recorded_files()
        args = ["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START, "--diff-paths", "-"]
        self.assertEqual(
            self._count(args, stdin_data="".join(f"{p}\0" for p in _DIFF)), "1"
        )


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


class TestStoryThreeFalseAbortE2E(_ScopedGateTestCase):
    """AC#8 — the exact scenario from concern 3542ad2915df.

    story-003's close cycle ran clean, but 964426f13819 (an unrelated open lock
    defect, severity high, untagged, recorded inside the close window, naming a
    file in story-005's domain) pushed the auto-merge gate to
    abort-recommended. With the close diff supplied, the gate stays at 0.
    """

    def setUp(self) -> None:
        super().setUp()
        # 964426f13819's shape, plus the noise a live SMM carries in the same
        # window: a resolved-elsewhere concern in another cycle and one with no
        # file pin at all.
        write_events(
            self.events_file,
            [
                _concern(files=[_OUTSIDE_DIFF]),
                _concern(files=["plugins/xp-agents/scripts/concern_conflicts.py"]),
                _concern(files=["plugins/xp-agents/smm/init.sh"], cycle=_OTHER_CYCLE),
            ],
        )
        self.story_003_diff = [
            "plugins/xp-agents/scripts/preload_liveness.py",
            "plugins/xp-agents/tests/hooks/test_preload_liveness.py",
        ]

    def test_gate_does_not_flip_to_abort_recommended(self) -> None:
        self.assertEqual(self._scoped(self.story_003_diff), "0")

    def test_gate_still_flips_when_the_concern_is_about_this_diff(self) -> None:
        """The other half of the guarantee: narrowing must not disarm the gate
        for a concern that IS about the code being merged."""
        self.assertEqual(
            self._scoped(
                [*self.story_003_diff, "plugins/xp-agents/scripts/concern_conflicts.py"]
            ),
            "1",
        )


class TestTaggingBeatsTheFilesInference(_ScopedGateTestCase):
    """The remedy this file's rule was only ever a fallback for.

    Diff relevance INFERS which concerns belong to a close from the `files` the
    author happened to record, so a stale or wrong path silently excludes a
    concern from the one gate that exists not to miss it. When a close is
    running, the appender records the answer instead — and a recorded answer
    outranks the inference.

    End-to-end on purpose: the concern is written by the real appender CLI (a
    different process from the close, which is the whole difficulty) and read
    by the real count-concerns query the shared Step 6 invokes.
    """

    def _append_concern_naming(self, path: str) -> None:
        result = run_cli(
            _APPEND_IMPL,
            [
                "--type", "concern",
                "--agent", "main",
                "--severity", "high",
                "--content", "Reviewer Block: the gate must still see this",
                "--files", json.dumps([path]),
            ],
            self.smm_dir,
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_concern_raised_during_the_close_counts_despite_its_files(self) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        self._append_concern_naming(_OUTSIDE_DIFF)
        self.assertEqual(
            self._scoped(_DIFF),
            "1",
            "a concern raised DURING this close carries its id, and the tag is "
            "authoritative — the files heuristic must not drop it",
        )

    def test_the_same_concern_outside_a_close_follows_the_files_rule(self) -> None:
        """The control, and AC#6: a concern written with no close running — the
        shape every concern in an existing SMM has — keeps exactly the shipped
        behaviour. The tag narrows the gate; its absence changes nothing."""
        self._append_concern_naming(_OUTSIDE_DIFF)
        self.assertEqual(self._scoped(_DIFF), "0")

    def test_another_sessions_close_does_not_capture_this_concern(self) -> None:
        """Two teammates closing at once against the shared SMM: the concern is
        raised in a session with no close of its own, so it must stay untagged
        rather than being pulled into the neighbour's cycle."""
        with patch.dict(os.environ, {"XP_SESSION_ID": "another-session"}):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        self._append_concern_naming("plugins/xp-agents/smm/smm_count.py")
        counted = self._count(["--cycle-id", _CYCLE, "--since-ts", _WINDOW_START])
        self.assertEqual(counted, "1", "an untagged concern still counts (fail closed)")
        self.assertIsNone(
            (self._read_events()[-1].get("metadata") or {}).get(
                METADATA_KEY_CLOSE_CYCLE_ID
            ),
            "the neighbour's cycle id must not reach this session's concern",
        )


if __name__ == "__main__":
    unittest.main()
