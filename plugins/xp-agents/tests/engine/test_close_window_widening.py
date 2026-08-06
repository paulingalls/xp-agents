#!/usr/bin/env python3
"""An enclosing close's concern gate can see the whole sprint.

`close_window.resolve` and `ConcernWindow.excludes_tag` at the unit boundary;
the same rule through the real `count-concerns` query lives in
`test_close_window_count_concerns.py`.

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
from _close_window_fixtures import (
    _CLOSE_START_TS,
    _ENCLOSING,
    _PREV_SPRINT_START,
    _PRIOR_SPRINT_CYCLE,
    _SPRINT_START,
    _STORY_CYCLE,
    _sprint_start,
)
from _count_concerns_fixtures import _close_started
from conftest import _SMMTestCase, make_sprint_dict


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

    def test_sprint_json_started_that_is_not_a_date_yields_no_floor(self) -> None:
        # `started` is REQUIRED by the sprint schema but its SHAPE is not
        # validated, and xp-sprint-start SKILL.md has an LLM author it. A value
        # like "TBD" sorts ABOVE every real ISO ts, so trusting it as a floor
        # excludes the ENTIRE log — widening the exclusion, the one direction
        # this module forbids, and silently: the count reads 0 and auto-merge
        # fires over the findings the gate exists to catch.
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(make_sprint_dict(started="TBD"))
        )
        window = self._resolve([_close_started(_ENCLOSING, "sprint", _CLOSE_START_TS)])
        self.assertIsNone(window.floor)
        self.assertIsNotNone(window.note)

    def test_malformed_sprint_start_event_ts_falls_through(self) -> None:
        # Same rule on the preferred leg: a ts that is not a date prefix is not
        # a floor. Falling through to the EARLIER sprint start only ever widens
        # the window, so the degradation stays fail-closed.
        window = self._resolve(
            [
                _sprint_start(_PREV_SPRINT_START, "sprint-006"),
                _sprint_start("soon", "sprint-007"),
                _close_started(_ENCLOSING, "sprint", _CLOSE_START_TS),
            ]
        )
        self.assertEqual(window.floor, _PREV_SPRINT_START)

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


if __name__ == "__main__":
    unittest.main()
