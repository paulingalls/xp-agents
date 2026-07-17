#!/usr/bin/env python3
"""Tests for session_history: ring-buffer + cascade-prune persistence.

session_history.py owns load/append/prune for session_history.json — the
persistent layer that survives across /xp-end-session invocations and
hands carry_forward items to the next session. Cascade-prune leans on
resolution.compute_resolutions so resolved events drop their carry_forward
entries automatically.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import session_history
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_ANSWER, EVENT_TYPE_QUESTION


def _entry(ts: str, summary: str, carry_forward: list[dict] | None = None) -> dict:
    return {
        "ts": ts,
        "summary": summary,
        "carry_forward": carry_forward or [],
    }


def _cf(note: str, references: list[str], recommendation: str = "triage") -> dict:
    return {"note": note, "references": references, "recommendation": recommendation}


class TestLoadHistory(_SMMTestCase):
    def test_load_missing_returns_empty_with_version_1(self):
        result = session_history.load_history(self.smm_dir)
        self.assertEqual(result, {"version": 1, "entries": []})

    def test_load_rejects_symlink_with_oserror(self):
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
        link = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            session_history.load_history(self.smm_dir)

    def test_load_raises_valueerror_on_corrupt_json(self):
        (self.smm_dir / session_history.SESSION_HISTORY_FILENAME).write_text(
            "{not json", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            session_history.load_history(self.smm_dir)


class TestSaveHistory(_SMMTestCase):
    def test_save_roundtrip_preserves_data(self):
        data = {
            "version": 1,
            "entries": [
                _entry("2026-05-01T00:00:00+00:00", "first session"),
                _entry(
                    "2026-05-02T00:00:00+00:00",
                    "second session",
                    [_cf("watch decision", ["aabbccddeeff"])],
                ),
            ],
        }
        session_history.save_history(self.smm_dir, data)
        result = session_history.load_history(self.smm_dir)
        self.assertEqual(result, data)

    def test_save_rejects_symlink_with_oserror(self):
        real = self.smm_dir / "real.json"
        original = json.dumps({"version": 1, "entries": []})
        real.write_text(original, encoding="utf-8")
        link = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            session_history.save_history(
                self.smm_dir,
                {"version": 1, "entries": [_entry("2026-05-01T00:00:00+00:00", "x")]},
            )
        # Underlying target unmodified
        self.assertEqual(real.read_text(encoding="utf-8"), original)

    def test_save_validates_before_write(self):
        with self.assertRaises(ValueError):
            session_history.save_history(self.smm_dir, {"entries": []})  # no version
        self.assertFalse(
            (self.smm_dir / session_history.SESSION_HISTORY_FILENAME).exists()
        )

    def test_save_rejects_non_string_references(self):
        # references is the one field prune_resolved relies on; bad shapes
        # must fail loud at save time, not silently survive the cascade.
        bad = {
            "version": 1,
            "entries": [
                {
                    "ts": "2026-05-01T00:00:00+00:00",
                    "summary": "x",
                    "carry_forward": [
                        {"note": "n", "references": [123], "recommendation": "r"}
                    ],
                }
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            session_history.save_history(self.smm_dir, bad)
        self.assertIn("references", str(ctx.exception))


class TestAppendEntry(_SMMTestCase):
    def test_append_entry_evicts_oldest_beyond_n5(self):
        for i in range(5):
            session_history.append_entry(
                self.smm_dir,
                _entry(f"2026-05-0{i + 1}T00:00:00+00:00", f"session {i + 1}"),
            )
        # 6th append evicts the first
        session_history.append_entry(
            self.smm_dir, _entry("2026-05-06T00:00:00+00:00", "session 6")
        )
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(len(data["entries"]), 5)
        self.assertEqual(data["entries"][0]["summary"], "session 2")
        self.assertEqual(data["entries"][-1]["summary"], "session 6")

    def test_seven_appends_yield_last_five_chronological(self):
        # AC-5 E2E: 7 appends -> last 5 in chronological order with version=1
        for i in range(7):
            session_history.append_entry(
                self.smm_dir,
                _entry(f"2026-05-0{i + 1}T00:00:00+00:00", f"session {i + 1}"),
            )
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["entries"]), 5)
        self.assertEqual(
            [e["summary"] for e in data["entries"]],
            ["session 3", "session 4", "session 5", "session 6", "session 7"],
        )


class TestPruneResolved(_SMMTestCase):
    def test_prune_resolved_drops_fully_resolved_carry_forward(self):
        question = make_event(EVENT_TYPE_QUESTION, content="ship date?")
        answer = make_event(
            EVENT_TYPE_ANSWER, content="2026-05-15", references=[question["id"]]
        )
        events = [question, answer]

        data = {
            "version": 1,
            "entries": [
                _entry(
                    "2026-05-01T00:00:00+00:00",
                    "session A",
                    [
                        _cf("answered question", [question["id"]]),
                        _cf("untouched", ["deadbeefcafe"]),
                    ],
                ),
            ],
        }
        session_history.save_history(self.smm_dir, data)

        pruned = session_history.prune_resolved(self.smm_dir, events)
        self.assertEqual(pruned, 1)

        result = session_history.load_history(self.smm_dir)
        remaining = result["entries"][0]["carry_forward"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["note"], "untouched")

    def test_prune_resolved_keeps_partially_resolved(self):
        question = make_event(EVENT_TYPE_QUESTION, content="A?")
        answer = make_event(
            EVENT_TYPE_ANSWER, content="yes", references=[question["id"]]
        )
        events = [question, answer]

        data = {
            "version": 1,
            "entries": [
                _entry(
                    "2026-05-01T00:00:00+00:00",
                    "session A",
                    [
                        # one ref resolved, one not — keep the item
                        _cf("partial", [question["id"], "deadbeefcafe"]),
                    ],
                ),
            ],
        }
        session_history.save_history(self.smm_dir, data)

        pruned = session_history.prune_resolved(self.smm_dir, events)
        self.assertEqual(pruned, 0)

        result = session_history.load_history(self.smm_dir)
        self.assertEqual(len(result["entries"][0]["carry_forward"]), 1)

    def test_prune_resolved_drops_item_whose_target_event_is_archived(self):
        """Resolver LIVE, target event ARCHIVED (absent from events.jsonl).

        The resolver closes via `metadata.resolves` naming the target id —
        NOT `references` — so this can only be caught by the raw
        claimed_resolved_ids term inside closed_target_ids. A
        references-shaped resolver would already pass under the old
        collect_all_resolved_ids-only implementation and prove nothing.
        """
        target_id = "abcdef123456"
        resolver = make_event(
            EVENT_TYPE_ANSWER,
            content="closing an archived item",
            metadata={"resolves": [target_id]},
        )
        # The target's own event is NOT in this list — it was archived.
        events = [resolver]

        data = {
            "version": 1,
            "entries": [
                _entry(
                    "2026-05-01T00:00:00+00:00",
                    "session A",
                    [_cf("stale note about archived target", [target_id])],
                ),
            ],
        }
        session_history.save_history(self.smm_dir, data)

        pruned = session_history.prune_resolved(self.smm_dir, events)
        self.assertEqual(pruned, 1)

        result = session_history.load_history(self.smm_dir)
        self.assertEqual(result["entries"][0]["carry_forward"], [])


class TestFilterSessionAnchorTimestamps(_SMMTestCase):
    """filter_session_anchor_timestamps extracts session_started ts values
    and sorts ascending. Sort is load-bearing — sessions_since_event uses
    bisect_right which requires ascending input. Events are normally
    monotonic on disk but clock skew across teammate worktrees can
    break the invariant, so the helper enforces it."""

    def test_empty_events_returns_empty_list(self):
        self.assertEqual(session_history.filter_session_anchor_timestamps([]), [])

    def test_no_session_started_events_returns_empty_list(self):
        events = [
            make_event(
                EVENT_TYPE_QUESTION, content="Q?", ts="2026-05-10T10:00:00+00:00"
            ),
            make_event(EVENT_TYPE_ANSWER, content="A.", ts="2026-05-10T11:00:00+00:00"),
        ]
        self.assertEqual(session_history.filter_session_anchor_timestamps(events), [])

    def test_extracts_ts_from_session_started_events_only(self):
        from event_schema import EVENT_TYPE_SESSION_STARTED

        events = [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start1",
                ts="2026-05-10T10:00:00+00:00",
            ),
            make_event(
                EVENT_TYPE_QUESTION, content="Q?", ts="2026-05-10T11:00:00+00:00"
            ),
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start2",
                ts="2026-05-11T09:00:00+00:00",
            ),
        ]
        result = session_history.filter_session_anchor_timestamps(events)
        self.assertEqual(
            result, ["2026-05-10T10:00:00+00:00", "2026-05-11T09:00:00+00:00"]
        )

    def test_sorts_ascending_even_when_input_out_of_order(self):
        """Sort is load-bearing; pin it. Append order on disk is
        normally monotonic but clock skew across teammate worktrees
        can produce out-of-order timestamps."""
        from event_schema import EVENT_TYPE_SESSION_STARTED

        events = [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start3",
                ts="2026-05-12T09:00:00+00:00",
            ),
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start1",
                ts="2026-05-10T10:00:00+00:00",
            ),
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start2",
                ts="2026-05-11T09:00:00+00:00",
            ),
        ]
        result = session_history.filter_session_anchor_timestamps(events)
        self.assertEqual(
            result,
            [
                "2026-05-10T10:00:00+00:00",
                "2026-05-11T09:00:00+00:00",
                "2026-05-12T09:00:00+00:00",
            ],
        )

    def test_skips_session_started_events_without_ts(self):
        from event_schema import EVENT_TYPE_SESSION_STARTED

        events = [
            make_event(EVENT_TYPE_SESSION_STARTED, content="missing-ts", ts=""),
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start1",
                ts="2026-05-10T10:00:00+00:00",
            ),
        ]
        result = session_history.filter_session_anchor_timestamps(events)
        self.assertEqual(result, ["2026-05-10T10:00:00+00:00"])


class TestComputeStaleness(_SMMTestCase):
    """Freshness classification of a session_history entry against the
    sorted list of session_started boundary anchors.

    Mechanics: the staleness render runs at kickoff, AFTER session_start.py
    has emitted the CURRENT session's session_started. So the newest anchor
    in the list is always the current still-running session, which is NOT a
    skipped session — it provides the same +1 the entry's own session_end
    used to provide under the old model. Therefore count==1 (only the
    current session's anchor is newer) means fresh; count>=2 means count-1
    sessions started without a summary in between.
    """

    _T1 = "2026-05-10T10:00:00+00:00"
    _T_CURRENT = "2026-05-11T09:00:00+00:00"  # current session's anchor (after T1)
    _T_NEXT2 = "2026-05-12T09:00:00+00:00"
    _T_NEXT3 = "2026-05-13T09:00:00+00:00"

    def test_no_anchors_returns_unknown(self):
        # Empty anchor list = no boundary data (e.g. pre-M1 log).
        entry = _entry(self._T1, "summary")
        result = session_history.compute_staleness(entry, [])
        self.assertEqual(result, {"status": "unknown", "skipped_sessions": 0})

    def test_zero_newer_anchors_is_unknown(self):
        # No anchor newer than the summary = no boundary crossed since it was
        # written (the summary is from the current still-running session).
        entry = _entry(self._T1, "summary")
        prior = "2026-05-10T09:00:00+00:00"  # before the summary
        result = session_history.compute_staleness(entry, [prior])
        self.assertEqual(result, {"status": "unknown", "skipped_sessions": 0})

    def test_one_newer_anchor_is_fresh(self):
        # The single newer anchor is the current session; the prior session
        # closed cleanly, nothing was skipped.
        entry = _entry(self._T1, "summary")
        result = session_history.compute_staleness(entry, [self._T_CURRENT])
        self.assertEqual(result, {"status": "fresh", "skipped_sessions": 0})

    def test_two_newer_anchors_is_stale_one_skipped(self):
        # Current session + one intervening session that started without a
        # summary => one skipped.
        entry = _entry(self._T1, "summary")
        result = session_history.compute_staleness(
            entry, [self._T_CURRENT, self._T_NEXT2]
        )
        self.assertEqual(result, {"status": "stale", "skipped_sessions": 1})

    def test_three_newer_anchors_is_stale_two_skipped(self):
        entry = _entry(self._T1, "summary")
        result = session_history.compute_staleness(
            entry, [self._T_CURRENT, self._T_NEXT2, self._T_NEXT3]
        )
        self.assertEqual(result, {"status": "stale", "skipped_sessions": 2})


class TestRenderMarkdown(_SMMTestCase):
    """Pure formatter for the LAST_SESSION markdown block."""

    def test_empty_entries_renders_empty_string(self):
        self.assertEqual(session_history.render_markdown([]), "")

    def test_one_entry_renders_block_with_summary(self):
        entries = [_entry("2026-05-10T10:00:00+00:00", "Shipped Track 2.")]
        result = session_history.render_markdown(entries)
        self.assertIn("### LAST_SESSION", result)
        self.assertIn("Shipped Track 2.", result)

    def test_entry_with_carry_forward_renders_note_and_recommendation(self):
        entries = [
            _entry(
                "2026-05-10T10:00:00+00:00",
                "Summary text.",
                [_cf("Watch this thing", ["abc"], "Investigate next session.")],
            )
        ]
        result = session_history.render_markdown(entries)
        self.assertIn("Summary text.", result)
        self.assertIn("Watch this thing", result)
        self.assertIn("Investigate next session.", result)
        # Event ids in references are NEVER rendered.
        self.assertNotIn("abc", result)

    def test_fresh_entry_renders_no_staleness_annotation(self):
        entries = [_entry("2026-05-10T10:00:00+00:00", "Summary.")]
        # One anchor newer than the summary = the current session; the prior
        # session closed cleanly => fresh, no annotation.
        result = session_history.render_markdown(
            entries, session_anchor_timestamps=["2026-05-10T10:00:30+00:00"]
        )
        self.assertIn("### LAST_SESSION", result)
        self.assertNotIn("(stale", result)
        self.assertNotIn("(unknown", result)

    def test_stale_entry_renders_inline_annotation_on_header(self):
        entries = [_entry("2026-05-10T10:00:00+00:00", "Summary.")]
        result = session_history.render_markdown(
            entries,
            session_anchor_timestamps=[
                "2026-05-10T10:00:30+00:00",
                "2026-05-11T09:00:00+00:00",
                "2026-05-12T09:00:00+00:00",
            ],
        )
        # Three anchors newer than the entry => count 3, skipped_sessions=2
        # (the newest is the current session; two intervening were skipped).
        self.assertIn("### LAST_SESSION (stale", result)
        self.assertIn("2 sessions", result)
        # Verb is "started", not "ended": the newest counted anchor is the
        # CURRENT still-running session, which has not ended.
        self.assertIn("started without /xp-end-session", result)
        self.assertNotIn("ended without", result)

    def test_unknown_status_renders_no_annotation(self):
        # No anchors at all — annotation suppressed to keep noise low.
        entries = [_entry("2026-05-10T10:00:00+00:00", "Summary.")]
        result = session_history.render_markdown(entries, session_anchor_timestamps=[])
        self.assertIn("### LAST_SESSION", result)
        self.assertNotIn("(stale", result)
        self.assertNotIn("(unknown", result)

    def test_only_most_recent_entry_carries_staleness_annotation(self):
        # When multiple entries render, only the most-recent (last in list)
        # gets the annotation — older entries are obviously old.
        entries = [
            _entry("2026-05-08T10:00:00+00:00", "Older summary."),
            _entry("2026-05-10T10:00:00+00:00", "Newer summary."),
        ]
        # Both would be "stale" by count, but the older one is rendered first
        # without annotation in the header — only the newer one's header
        # carries the marker.
        result = session_history.render_markdown(
            entries,
            session_anchor_timestamps=[
                "2026-05-10T10:00:30+00:00",
                "2026-05-11T09:00:00+00:00",
                "2026-05-12T09:00:00+00:00",
            ],
        )
        # Single block header with the (stale ...) annotation; both
        # entries follow under that one header (matches the original
        # render_history.py format).
        self.assertEqual(result.count("(stale"), 1)
        self.assertEqual(result.count("### LAST_SESSION"), 1)
        stale_pos = result.find("(stale")
        older_pos = result.find("Older summary.")
        newer_pos = result.find("Newer summary.")
        # Header (with stale annotation) precedes both bodies; bodies
        # follow in chronological order.
        self.assertLess(stale_pos, older_pos)
        self.assertLess(older_pos, newer_pos)
