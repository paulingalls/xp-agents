#!/usr/bin/env python3
"""An enclosing close's concern gate can see the whole sprint.

Concern f106bf044ded / decision efed0cb00c62: the merge gate whose entire
purpose is to catch a story-close's unfixed findings could not see them. A
story-close records a concern tagged with its own cycle id; the later
sprint/plan/free close mints a FRESH cycle id and a fresh CLOSE_START_TS, and
the earlier concern was dropped twice over independently — its tag differed
from the gated cycle, AND its ts predated the enclosing close's start. Fixing
one filter changed nothing, which is why the previous attempt shipped no code.

Both filters now consult one window (`smm/close_window.py`), and both are keyed
off ONE decision — the gated cycle's own `close_mode` — so the two spellings of
the rule cannot drift apart the way this module drifted before. A `story` close
keeps today's narrow window: widening it too would switch story-close auto-merge
off for most closes late in a sprint, since every earlier story's leftovers
would count.

The direction of every fail-safe here is COUNT: an unresolvable window, an
unresolvable mode, or a tag that joins to no `close_started` all mean the
concern counts. Narrowing the gate is acceptable; widening the EXCLUSION is the
one thing that is not.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import close_window
from _count_concerns_fixtures import _CLI, _close_started, _concern
from conftest import _SMMTestCase, make_event, make_sprint_dict, run_cli, write_events
from event_schema import EVENT_TYPE_SPRINT, EVENT_TYPE_STATUS

_SPRINT_START = "2026-07-20T09:00:00+00:00"
_PREV_SPRINT_START = "2026-06-01T09:00:00+00:00"

# The enclosing close being gated, and the story-close that ran earlier in the
# same sprint and left a concern behind.
_ENCLOSING = "eeee00001111"
_STORY_CYCLE = "550011122233"
_PRIOR_SPRINT_CYCLE = "0dd000111222"

# The enclosing close starts LATE in the sprint — that gap between the sprint
# start and CLOSE_START_TS is the hole this story closes.
_CLOSE_START_TS = "2026-07-28T12:00:00+00:00"


def _sprint_start(ts: str = _SPRINT_START, sprint_id: str = "sprint-007") -> dict:
    """A `type=sprint`, `metadata.action=start` event — the sprint window bound.

    Preferred over sprint.json's date-only `started`: better granularity and no
    extra file read, since `count-concerns` already iterates these events.
    """
    return make_event(
        EVENT_TYPE_SPRINT, ts=ts, metadata={"sprint_id": sprint_id, "action": "start"}
    )


class TestResolveFloor(_SMMTestCase):
    """`close_window.resolve` picks the floor from the gated close's MODE."""

    def _resolve(
        self,
        events: list[dict],
        cycle_id: str | None = _ENCLOSING,
        since_ts: str | None = _CLOSE_START_TS,
    ) -> close_window.ConcernWindow:
        return close_window.resolve(
            events, self.smm_dir, cycle_id=cycle_id, since_ts=since_ts
        )

    def test_story_mode_keeps_the_narrow_floor(self) -> None:
        # AC4: widening a story close would count every earlier story's
        # leftovers and disable its auto-merge sprint-wide.
        window = self._resolve(
            [_sprint_start(), _close_started(_ENCLOSING, "story", _CLOSE_START_TS)]
        )
        self.assertEqual(window.floor, _CLOSE_START_TS)
        self.assertFalse(window.widened)
        self.assertIsNone(window.note)

    def test_enclosing_modes_use_the_sprint_start(self) -> None:
        for mode in ("sprint", "plan", "free"):
            with self.subTest(mode=mode):
                window = self._resolve(
                    [
                        _sprint_start(),
                        _close_started(_ENCLOSING, mode, _CLOSE_START_TS),
                    ]
                )
                self.assertEqual(window.floor, _SPRINT_START)
                self.assertTrue(window.widened)
                self.assertIsNone(window.note)

    def test_latest_sprint_start_event_wins(self) -> None:
        window = self._resolve(
            [
                _sprint_start(_PREV_SPRINT_START, "sprint-006"),
                _sprint_start(),
                _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
            ]
        )
        self.assertEqual(window.floor, _SPRINT_START)

    def test_sprint_json_started_is_the_fallback_bound(self) -> None:
        # No sprint/start event in the log (compacted away, or a sprint older
        # than the event) — sprint.json still carries a date-only `started`,
        # which is a valid lexicographic floor against a full ISO ts.
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(make_sprint_dict(started="2026-07-20"))
        )
        window = self._resolve([_close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)])
        self.assertEqual(window.floor, "2026-07-20")
        self.assertTrue(window.widened)

    def test_unresolvable_sprint_window_drops_the_floor_entirely(self) -> None:
        # NEVER fall back to the passed --since-ts: that is exactly the
        # exclusion this story exists to close.
        window = self._resolve([_close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)])
        self.assertIsNone(window.floor)
        self.assertTrue(window.widened)
        self.assertIsNotNone(window.note)

    def test_cycle_with_no_close_started_gets_the_widest_floor(self) -> None:
        # AC4 second half: 4 of the 13 tagged cycle ids in the live log predate
        # the close_started event entirely. An unjoinable cycle is unreadable
        # evidence, so the gate must see everything rather than trust
        # --since-ts.
        window = self._resolve([_sprint_start()])
        self.assertIsNone(window.floor)
        self.assertFalse(window.widened)
        self.assertIsNotNone(window.note)

    def test_blank_close_mode_gets_the_widest_floor(self) -> None:
        window = self._resolve(
            [_sprint_start(), _close_started(_ENCLOSING, "   ", _CLOSE_START_TS)]
        )
        self.assertIsNone(window.floor)
        self.assertFalse(window.widened)

    def test_no_cycle_id_gets_the_widest_floor(self) -> None:
        window = self._resolve([_sprint_start()], cycle_id=None)
        self.assertIsNone(window.floor)
        self.assertIsNotNone(window.note)

    def test_no_since_ts_and_no_cycle_id_is_silent(self) -> None:
        # Nothing was dropped, so there is nothing to narrate — a note on every
        # unscoped call would train the operator to ignore the line that
        # matters.
        window = self._resolve([], cycle_id=None, since_ts=None)
        self.assertIsNone(window.floor)
        self.assertIsNone(window.note)

    def test_latest_close_started_for_a_cycle_wins(self) -> None:
        window = self._resolve(
            [
                _sprint_start(),
                _close_started(_ENCLOSING, "story", "2026-07-28T11:00:00+00:00"),
                _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
            ]
        )
        self.assertTrue(window.widened)


class TestExcludesTag(_SMMTestCase):
    """A tag excludes only when its close is PROVABLY outside the window."""

    def _window(self, mode: str, extra: list[dict] | None = None):
        events = [
            _sprint_start(),
            _close_started(_ENCLOSING, mode, _CLOSE_START_TS),
            *(extra or []),
        ]
        return close_window.resolve(
            events, self.smm_dir, cycle_id=_ENCLOSING, since_ts=_CLOSE_START_TS
        )

    def test_the_gated_cycles_own_tag_never_excludes(self) -> None:
        self.assertFalse(self._window("sprint").excludes_tag(_ENCLOSING))

    def test_untagged_never_excludes(self) -> None:
        self.assertFalse(self._window("sprint").excludes_tag(None))

    def test_earlier_story_close_in_this_sprint_counts(self) -> None:
        # AC2, the defect itself.
        window = self._window(
            "sprint",
            [_close_started(_STORY_CYCLE, "story", "2026-07-22T10:00:00+00:00")],
        )
        self.assertFalse(window.excludes_tag(_STORY_CYCLE))

    def test_close_from_a_previous_sprint_still_excludes(self) -> None:
        # AC3: widening must not re-admit prior-sprint noise.
        window = self._window(
            "sprint",
            [_close_started(_PRIOR_SPRINT_CYCLE, "story", _PREV_SPRINT_START)],
        )
        self.assertTrue(window.excludes_tag(_PRIOR_SPRINT_CYCLE))

    def test_tag_with_no_close_started_counts(self) -> None:
        # 12 of the 33 tagged open concerns in the live log are tagged with a
        # cycle that has no close_started at all. Unjoinable is unreadable
        # evidence, never licence to exclude — the same rule
        # concern_relevance._names_existing_code applies to a path that does
        # not exist.
        self.assertFalse(self._window("sprint").excludes_tag("f00dcafe1234"))

    def test_tag_whose_close_started_has_no_ts_counts(self) -> None:
        orphan = _close_started("beef00011122", "story", "2026-07-22T10:00:00+00:00")
        del orphan["ts"]
        window = self._window("sprint", [orphan])
        self.assertFalse(window.excludes_tag("beef00011122"))

    def test_unresolvable_sprint_window_excludes_nothing(self) -> None:
        # Widened but blind: the interface contract is honoured literally —
        # when the window cannot be resolved, the concern counts.
        window = close_window.resolve(
            [_close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)],
            self.smm_dir,
            cycle_id=_ENCLOSING,
            since_ts=_CLOSE_START_TS,
        )
        self.assertFalse(window.excludes_tag(_PRIOR_SPRINT_CYCLE))

    def test_story_mode_keeps_shipped_cross_cycle_isolation(self) -> None:
        # Decision 9feaf9a9cb94: the tag rule widens with the floor, off the
        # SAME mode decision. A story close keeps the concurrent-close
        # isolation --cycle-id was introduced for.
        window = self._window(
            "story",
            [_close_started(_STORY_CYCLE, "story", "2026-07-22T10:00:00+00:00")],
        )
        self.assertTrue(window.excludes_tag(_STORY_CYCLE))

    def test_unresolvable_mode_keeps_shipped_cross_cycle_isolation(self) -> None:
        window = close_window.resolve(
            [_sprint_start()],
            self.smm_dir,
            cycle_id=_ENCLOSING,
            since_ts=_CLOSE_START_TS,
        )
        self.assertTrue(window.excludes_tag(_STORY_CYCLE))


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
