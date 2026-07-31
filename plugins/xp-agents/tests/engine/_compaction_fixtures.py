#!/usr/bin/env python3
"""Machinery for driving a compaction that really does archive the intent.

Shared by the two suites `test_compact_adoption.py` was split into at 500 lines.

The load-bearing part is `_assert_archived`: every test built on this base runs a
REAL compaction and asserts the adopting event is GENUINELY GONE from
events.jsonl before asserting the intent survives. A test that left the event on
disk would pass without compaction having archived anything -- green today, and
still green after a regression that deletes the ledger.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import adoption_store
import compact
import intent
import materialize
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_SESSION_STARTED, EVENT_TYPE_STATUS

TRY_ID = "aa11bb22cc33"


class _LedgerCompactionTestCase(_SMMTestCase):
    """Machinery for driving a compaction that really does archive the intent."""

    def _anchors(self, count: int = 4) -> list[dict]:
        """Session boundary anchors, dated past the writer's clock.

        An adopt `decision` is retained for _DECISION_MAX_AGE (3) sessions —
        counted as anchors NEWER than the decision's own `ts`. The adopt fixtures
        go through the real writer, which stamps `ts` with the wall clock, so
        anchors dated in the fixture's own past would age the decision by ZERO
        sessions and it would never be archived. The far-future date is what makes
        this suite exercise compaction at all.
        """
        return [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content=f"start {i}",
                ts=f"2099-01-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(count)
        ]

    def _compact(self, pre_watermark: list[dict]) -> list[dict]:
        """Write *pre_watermark* + one uncurated trailing event, compact, and
        return the events that SURVIVED. The trailing event keeps the watermark
        honest: compaction only archives what has been curated."""
        trailing = make_event(
            EVENT_TYPE_STATUS, content="uncurated", ts="2026-06-01T00:00:00+00:00"
        )
        self._write_events([*pre_watermark, trailing])
        materialize.write_curation_watermark(
            self.smm_dir, len(pre_watermark), "xp-housekeeper"
        )
        compact.compact_after_curation(self.smm_dir)
        return self._read_events()

    def _assert_archived(self, live: list[dict], event: dict, what: str) -> None:
        """The falsifiability guard. Every surviving-intent assertion below is
        worthless unless the event carrying that intent is really gone."""
        self.assertNotIn(
            event["id"],
            {e["id"] for e in live},
            f"{what} is still in events.jsonl — compaction did not archive it, "
            f"so this test proves nothing about surviving compaction",
        )

    def _ledger(self) -> dict:
        return adoption_store.load_adoption(self.smm_dir)

    def _retro_map(self, live: list[dict]) -> dict:
        return intent.build_retro_intent_map(
            live, intent.retro_try_ids(live), ledger=self._ledger()
        )

    def _triage_map(self, live: list[dict]) -> dict:
        return intent.build_triage_intent_map(live, ledger=self._ledger())
