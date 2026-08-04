#!/usr/bin/env python3
"""The widened window end-to-end through the `count-concerns` CLI.

`test_close_window_widening.py` pins `close_window.resolve`/`excludes_tag`
directly; this file drives the same rule through the actual query the close
pipeline's Step 6 auto-merge gate runs, so the wiring in `smm_count` — the tag
rule AND both floor sites reading ONE window — is covered as the operator
experiences it rather than only at the unit boundary.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _close_window_fixtures import (
    _CLOSE_START_TS,
    _ENCLOSING,
    _PREV_SPRINT_START,
    _PRIOR_SPRINT_CYCLE,
    _STORY_CYCLE,
    _sprint_start,
)
from _count_concerns_fixtures import _CLI, _close_started, _concern
from conftest import _SMMTestCase, make_event, make_sprint_dict, run_cli, write_events
from event_schema import EVENT_TYPE_STATUS


class TestCountConcernsWidening(_SMMTestCase):
    """End-to-end through the CLI the close pipeline actually runs."""

    def _count(self, events: list[dict], cycle_id: str = _ENCLOSING) -> str:
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--cycle-id",
                cycle_id,
                "--since-ts",
                _CLOSE_START_TS,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_enclosing_close_counts_an_earlier_story_closes_concern(self) -> None:
        # AC2 through the real query. The concern is dropped twice over today:
        # its tag differs from the gated cycle AND its ts predates
        # CLOSE_START_TS. Both have to lift for this to count.
        events = [
            _sprint_start(),
            _close_started(_STORY_CYCLE, "story", "2026-07-22T10:00:00+00:00"),
            _concern(
                "high",
                ts="2026-07-22T10:30:00+00:00",
                metadata={"close_cycle_id": _STORY_CYCLE},
            ),
            _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
        ]
        self.assertEqual(self._count(events), "1")

    def test_enclosing_close_counts_an_untagged_mid_sprint_concern(self) -> None:
        events = [
            _sprint_start(),
            _concern("high", ts="2026-07-22T10:30:00+00:00", metadata={}),
            _close_started(_ENCLOSING, "plan", _CLOSE_START_TS),
        ]
        self.assertEqual(self._count(events), "1")

    def test_enclosing_close_excludes_a_previous_sprints_concern(self) -> None:
        # AC3 through the real query: BOTH filters must keep it out — its ts
        # predates the sprint start and its tag's close does too.
        events = [
            _close_started(_PRIOR_SPRINT_CYCLE, "story", _PREV_SPRINT_START),
            _concern(
                "high",
                ts="2026-06-02T10:30:00+00:00",
                metadata={"close_cycle_id": _PRIOR_SPRINT_CYCLE},
            ),
            _sprint_start(),
            _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
        ]
        self.assertEqual(self._count(events), "0")

    def test_story_close_keeps_its_narrow_window(self) -> None:
        # AC4 through the real query: the same mid-sprint leftovers that an
        # enclosing close must see stay invisible to a story close.
        events = [
            _sprint_start(),
            _close_started(_STORY_CYCLE, "story", "2026-07-22T10:00:00+00:00"),
            _concern(
                "high",
                ts="2026-07-22T10:30:00+00:00",
                metadata={"close_cycle_id": _STORY_CYCLE},
            ),
            _concern("high", ts="2026-07-22T11:00:00+00:00", metadata={}),
            _close_started(_ENCLOSING, "story", _CLOSE_START_TS),
            _concern("high", ts="2026-07-28T13:00:00+00:00", metadata={}),
        ]
        self.assertEqual(self._count(events), "1")

    def test_corrupt_line_floor_uses_the_same_widened_bound(self) -> None:
        # Two spellings of one rule is how this module drifted before: the
        # corrupt-line floor must resolve the bound identically. A line whose
        # embedded ts sits between the sprint start and CLOSE_START_TS is IN
        # the widened window, so it stays on the fail-closed floor.
        write_events(
            self.events_file,
            [_sprint_start(), _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)],
        )
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-07-22T10:00:00+00:00", "type": "conce\n')
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--cycle-id",
                _ENCLOSING,
                "--since-ts",
                _CLOSE_START_TS,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_before_the_sprint_is_still_excluded(self) -> None:
        write_events(
            self.events_file,
            [_sprint_start(), _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)],
        )
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-06-02T10:00:00+00:00", "type": "conce\n')
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--cycle-id",
                _ENCLOSING,
                "--since-ts",
                _CLOSE_START_TS,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")
        self.assertIn("provably out of scope", result.stderr)

    def test_garbage_sprint_json_started_still_counts_the_concern(self) -> None:
        # The floor fail-open through the real query: with an unusable `started`
        # and no sprint-start event, the enclosing close must count everything
        # rather than read 0 and auto-merge.
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(make_sprint_dict(started="TBD"))
        )
        events = [
            _concern("high", ts="2026-07-22T10:30:00+00:00", metadata={}),
            _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
        ]
        self.assertEqual(self._count(events), "1")

    def test_count_classifications_window_is_untouched(self) -> None:
        # OUT of scope by contract: it asks "were ask-route items raised during
        # THIS close?", where a narrow window is correct. Widening it would
        # wrongly block auto-merge on an EARLIER close's ask items.
        write_events(
            self.events_file,
            [
                _sprint_start(),
                make_event(
                    EVENT_TYPE_STATUS,
                    ts="2026-07-22T10:30:00+00:00",
                    working_on=[],
                    metadata={"action": "concern_classify", "route": "ask"},
                ),
                _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
            ],
        )
        result = run_cli(
            _CLI,
            [
                "count-classifications",
                "--route",
                "ask",
                "--cycle-id",
                _ENCLOSING,
                "--since-ts",
                _CLOSE_START_TS,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
