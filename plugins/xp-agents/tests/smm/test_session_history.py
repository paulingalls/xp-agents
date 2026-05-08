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
from resolution import compute_resolutions


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
        resolutions = compute_resolutions([question, answer])

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

        pruned = session_history.prune_resolved(self.smm_dir, resolutions)
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
        resolutions = compute_resolutions([question, answer])

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

        pruned = session_history.prune_resolved(self.smm_dir, resolutions)
        self.assertEqual(pruned, 0)

        result = session_history.load_history(self.smm_dir)
        self.assertEqual(len(result["entries"][0]["carry_forward"]), 1)
