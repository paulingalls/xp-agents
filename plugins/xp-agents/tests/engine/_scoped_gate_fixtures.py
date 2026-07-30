#!/usr/bin/env python3
"""The scoped close-gate harness: constants, concern factory, base case.

Shared by the four suites `test_count_concerns_cycle_isolation.py` was split
into at 590 lines. `--repo-root` points at a synthetic working tree rather than
this repo, so no fixture depends on a real file surviving a sibling story's
deletions.

Note `_concern` here is NOT the one in `_count_concerns_fixtures.py`: this one
defaults to high severity, stamps a close-cycle id, timestamps inside the close
window, and OMITS `files` entirely when asked — the shape a concern raised
without `--files` has, which the diff-relevance rule turns on. They look alike
and are not interchangeable.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, make_event, run_cli
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
