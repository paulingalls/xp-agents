#!/usr/bin/env python3
"""Staleness is DERIVED from age, not a new fact (story-015).

triage_preload.format_triage_section already annotates every open concern
with its age at render time ("(N sessions old)"). SessionStart must not also
emit a second, separate flag-concern to say the same thing — that produces a
concern the render can never resolve (only hand-drop), doubling the open-item
count for no new information.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

import triage_preload
from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)

_OLD_TS = "2026-01-01T00:00:00+00:00"
_ANCHOR_TS = [
    "2026-01-05T00:00:00+00:00",
    "2026-01-10T00:00:00+00:00",
    "2026-01-15T00:00:00+00:00",
    "2026-01-20T00:00:00+00:00",
]


class TestStaleConcernNoLongerFlagged(_HookTestCase):
    """SessionStart must not emit a redundant staleness concern (AC1, AC3, AC5)."""

    def _concerns(self) -> list[dict]:
        return [e for e in self._read_events() if e.get("type") == EVENT_TYPE_CONCERN]

    def test_no_new_concern_for_old_open_concern(self):
        import session_start

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern", ts=_OLD_TS)
        self._write_events(
            [c] + [make_event(EVENT_TYPE_SESSION_STARTED, ts=t) for t in _ANCHOR_TS]
        )
        before = len(self._concerns())

        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )

        after = self._concerns()
        self.assertEqual(len(after), before, "no new concern should be appended")
        self.assertEqual({e["id"] for e in after}, {c["id"]})

    def test_two_session_starts_do_not_grow_open_count(self):
        import session_start

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern", ts=_OLD_TS)
        self._write_events(
            [c] + [make_event(EVENT_TYPE_SESSION_STARTED, ts=t) for t in _ANCHOR_TS]
        )

        session_start.run(
            {"session_id": "t1", "source": "startup"}, smm_dir=self.smm_dir
        )
        after_first = len(self._concerns())

        session_start.run(
            {"session_id": "t2", "source": "startup"}, smm_dir=self.smm_dir
        )
        after_second = len(self._concerns())

        self.assertEqual(after_second, after_first)


class TestTriageRenderAnnotatesAgeInline(_HookTestCase):
    """The triage render is the sole staleness annotation (AC2, AC4)."""

    def test_open_concern_renders_once_with_age_annotation(self):
        import session_start

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern", ts=_OLD_TS)
        self._write_events(
            [c] + [make_event(EVENT_TYPE_SESSION_STARTED, ts=t) for t in _ANCHOR_TS]
        )

        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )

        output = triage_preload.run(self.smm_dir)
        self.assertEqual(output.count("Old concern"), 1)
        # 4 pre-existing anchors + the anchor this run itself appends = 5.
        self.assertIn("5 sessions old", output)
        self.assertNotIn("is stale", output)
        self.assertNotIn("flagged_stale", output)

    def test_resolved_stale_concern_does_not_render(self):
        c = make_event(EVENT_TYPE_CONCERN, content="Old concern", ts=_OLD_TS)
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=[],
            metadata={"resolves": [c["id"]]},
        )
        self._write_events(
            [c, resolver]
            + [make_event(EVENT_TYPE_SESSION_STARTED, ts=t) for t in _ANCHOR_TS]
        )

        output = triage_preload.run(self.smm_dir)
        self.assertNotIn("Old concern", output)


if __name__ == "__main__":
    unittest.main()
