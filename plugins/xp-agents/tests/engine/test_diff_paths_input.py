#!/usr/bin/env python3
"""How `--diff-paths` READS its input, and what it does when it cannot.

Split from `test_count_concerns_cycle_isolation.py` (590 lines). Grouped by
input handling rather than by the rule: a `--diff-paths` that parses to an empty
set must behave EXACTLY as if it were never supplied, because "no entry
intersects" is vacuously TRUE against an empty set — the one way the whole
narrowing could fail OPEN. Keep these if the implementation is ever refactored.
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
    _OUTSIDE_DIFF,
    _WINDOW_START,
    _concern,
    _ScopedGateTestCase,
)
from conftest import run_cli, write_events


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


if __name__ == "__main__":
    unittest.main()
