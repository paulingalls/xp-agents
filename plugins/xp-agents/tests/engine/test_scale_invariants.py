#!/usr/bin/env python3
"""Scale invariants for the SMM engine: parse cost proportional to the delta.

The assertions here run on every commit and in CI — they assert on WHAT gets
parsed, so they hold on any machine at any load. They replaced a tier of
wall-clock timers that measured the machine rather than the diff; that tier is
retired, and test_lefthook_perf_gate.py pins its absence.

Split from test_maintenance.py.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
import read_delta
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_SESSION_END


def _generate_mixed_events(count: int) -> list[dict]:
    """Generate a realistic distribution of events."""
    import random

    rng = random.Random(42)  # deterministic for reproducibility
    type_weights = [
        ("customer_input", 25),
        ("status", 20),
        ("decision", 8),
        ("convention", 5),
        ("concern", 8),
        ("discovery", 5),
        ("question", 8),
        ("answer", 5),
        ("assumption", 4),
        ("session_end", 2),
        ("goal", 1),
        ("debt", 1),
    ]
    types = []
    for t, w in type_weights:
        types.extend([t] * w)

    events = []
    for i in range(count):
        etype = rng.choice(types)
        ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}+00:00"
        events.append(make_event(etype, content=f"event-{i}", ts=ts))
    return events


class TestReadDeltaParseCost(_SMMTestCase):
    """Parse cost is proportional to the DELTA, not to total history.

    read_events_from walks a byte offset and hands parse_jsonl only raw[offset:]
    (read_delta.py:69-70). If that offset walk ever regresses to parsing the whole
    file, every agent's every read becomes O(total history) — the defect the old
    50ms wall-clock bound was standing in for. Asserting on WHAT gets parsed rather
    than on how long it took holds on any machine at any load.
    """

    def _raw_handed_to_parse(self, watermark: int) -> list[str]:
        """Run read_delta over 1000 events at `watermark`, capturing every raw
        string handed to parse_jsonl. parse_jsonl is imported into read_delta's
        namespace (read_delta.py:16), so it is directly patchable there.

        parse_jsonl is a plain function, so `wraps` delegates to the real one and
        records its args — unlike repair, which needs a hand-rolled stand-in
        because a mock attribute cannot serve as its `except` clause.
        """
        self._write_events(_generate_mixed_events(1000))
        read_delta.write_watermark(self.smm_dir, "bench", watermark)

        with patch.object(
            read_delta, "parse_jsonl", wraps=read_delta.parse_jsonl
        ) as spy:
            read_delta.read_delta(self.smm_dir, "bench")
        return [call.args[0] for call in spy.call_args_list]

    def test_parses_only_the_tail_past_the_watermark(self):
        seen = self._raw_handed_to_parse(500)

        self.assertEqual(len(seen), 1, "read_delta must parse in a single pass")
        parsed = seen[0]
        self.assertEqual(
            len(parsed.splitlines()),
            500,
            "parse_jsonl must receive only the 500-line tail past the watermark, "
            "not all 1000 lines — parse cost has to track the delta, not history",
        )
        self.assertNotIn(
            '"content": "event-0"',
            parsed,
            "the pre-watermark head was re-parsed — the offset walk is broken",
        )
        self.assertIn('"content": "event-999"', parsed)

    def test_watermark_zero_parses_everything(self):
        """Positive control for the assertion above (decision 308dd829d2a4).

        Same fixture, same spy, one delta: nothing has been read yet, so the whole
        file IS the delta and parse_jsonl must receive all 1000 lines. That is what
        proves the 500-line result above is WATERMARK-DRIVEN — a read_delta that
        parsed a fixed-size window, or one whose offset walk ignored the watermark
        in the same direction every time, satisfies the tail-only assertion alone.
        """
        seen = self._raw_handed_to_parse(0)

        self.assertEqual(len(seen), 1, "read_delta must parse in a single pass")
        parsed = seen[0]
        self.assertEqual(
            len(parsed.splitlines()),
            1000,
            "with no watermark the whole file is the delta — the spy must see it "
            "all, or it is not watching the parse at all",
        )
        self.assertIn('"content": "event-0"', parsed)


class TestCompactParseCost(_SMMTestCase):
    """Compaction parses the log once, and actually reaches the archive path.

    Both are invariants the old compact wall-clock timer stood in for — but its
    liveness check (`archived > 0`) lived INSIDE the gated timer, so it only ran
    where XP_PERF was set, which CI never does. A second parse pass, or an early
    exit before the retention split, is caught here deterministically on any
    machine at any load.
    """

    def _compact_with_spy(self) -> tuple[dict, list[str]]:
        """Compact a log with a curation watermark, capturing every raw string
        handed to parse_jsonl.

        compact imports parse_jsonl into its own namespace (compact.py:44), so it
        is directly patchable there; `wraps` delegates to the real function and
        records its args.

        The curation watermark is what makes this a compaction at all: without
        one, compact_after_curation early-exits before the retention split.
        """
        import compact

        events = _generate_mixed_events(200)
        for i in range(10):
            events.append(
                make_event(
                    EVENT_TYPE_SESSION_END,
                    content=f"end-{i}",
                    working_on=[],
                    ts=f"2026-02-{i + 1:02d}T00:00:00+00:00",
                )
            )
        self._write_events(events)
        materialize.write_curation_watermark(
            self.smm_dir, len(events) // 2, "xp-housekeeper"
        )

        with patch.object(compact, "parse_jsonl", wraps=compact.parse_jsonl) as spy:
            result = compact.compact(self.smm_dir)
        return result, [call.args[0] for call in spy.call_args_list]

    def test_compact_parses_the_log_in_a_single_pass(self):
        _, seen = self._compact_with_spy()

        self.assertEqual(
            len(seen),
            1,
            f"compact handed parse_jsonl {len(seen)} raw strings — a second pass "
            "makes compaction cost a multiple of history, which the old wall-clock "
            "bound could only notice as a slowdown, and only on a quiet box",
        )

    def test_compact_reaches_the_archive_path(self):
        """The liveness the gated timer used to carry, and what makes the count
        above mean something.

        "Exactly one parse" is also what a compaction that bailed out early looks
        like: it reads, parses once, and archives nothing. Pinning `archived > 0`
        and the whole log reaching parse_jsonl is what separates one honest pass
        from one aborted one.
        """
        result, seen = self._compact_with_spy()

        self.assertGreater(
            result["archived"], 0, "compaction never reached the archive path"
        )
        self.assertEqual(len(seen), 1, "the spy is not watching the parse at all")
        self.assertIn(
            '"content": "event-0"',
            seen[0],
            "compact must be handed the whole log — the spy saw only part of it",
        )


class TestMixedEventGenerator(_SMMTestCase):
    """The shared scale fixture itself — the structural invariants above build
    on it, so it has to stay honest."""

    def test_mixed_event_generator_distribution(self):
        """Verify _generate_mixed_events produces expected types."""
        events = _generate_mixed_events(100)
        types = {e["type"] for e in events}
        # Should have at least a few different types
        self.assertGreater(len(types), 5)
        # All should be valid events
        for e in events:
            self.assertIn("id", e)
            self.assertIn("type", e)


if __name__ == "__main__":
    unittest.main()
