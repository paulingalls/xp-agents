#!/usr/bin/env python3
"""Tests for `smm_cli.py count-classifications` subcommand.

The subcommand counts events with `metadata.action == "concern_classify"`
optionally filtered by `--route` (fix|ask) and `--since-ts` (ISO 8601
timestamp). Used by the story-close + free-close auto-merge override
to verify Step 5c queued zero ask-user items via a structured filter
instead of content-string regex.

Lives in its own file (not test_smm_cli.py) because the subcommand has
its own concern (event-stream filtering, not pillar curation) and the
test surface for the new filter combinations earns a focused file.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli, write_events
from event_schema import EVENT_TYPE_STATUS

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"


def _classify_event(
    *,
    route: str,
    category: str = "lint",
    concern_id: str = "abcdef012345",
    ts: str = "2026-05-01T00:00:00+00:00",
    close_cycle_id: str | None = None,
) -> dict:
    metadata = {
        "action": "concern_classify",
        "route": route,
        "category": category,
        "concern_id": concern_id,
    }
    if close_cycle_id is not None:
        metadata["close_cycle_id"] = close_cycle_id
    return {
        "id": "0123456789ab",
        "ts": ts,
        "type": EVENT_TYPE_STATUS,
        "agent_id": "main",
        "content": f"concern-classify {concern_id}: {route} ({category}) — test",
        "schema_version": 1,
        "working_on": [],
        "metadata": metadata,
    }


class TestCountClassifications(_SMMTestCase):
    """Each filter combination + edge cases for the count subcommand.

    `_SMMTestCase.setUp` creates a fresh tmp SMM dir per test and
    pre-touches `events.jsonl`, so no test starts with a stale log.
    """

    def test_returns_zero_when_no_events_file(self) -> None:
        # Plugin ships to repos that may have no SMM yet — the CLI must
        # gracefully return 0 not raise FileNotFoundError. Remove the
        # touched events.jsonl to simulate the pre-config state.
        self.events_file.unlink()
        result = run_cli(_CLI, ["count-classifications"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_returns_zero_when_no_concern_classify_events(self) -> None:
        # Other status events (file_write, qr_complete, etc.) must NOT
        # be counted — only metadata.action=concern_classify counts.
        other = {
            "id": "ffffffffffff",
            "ts": "2026-05-01T00:00:00+00:00",
            "type": EVENT_TYPE_STATUS,
            "agent_id": "main",
            "content": "some other status",
            "schema_version": 1,
            "working_on": [],
            "metadata": {"action": "qr_complete"},
        }
        write_events(self.events_file, [other])
        result = run_cli(_CLI, ["count-classifications"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_counts_all_concern_classify_when_no_filters(self) -> None:
        # No --route filter means count ALL classification events
        # regardless of route — useful for auditing / total-volume checks.
        events = [
            _classify_event(route="fix"),
            _classify_event(route="ask"),
            _classify_event(route="fix"),
        ]
        write_events(self.events_file, events)
        result = run_cli(_CLI, ["count-classifications"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "3")

    def test_route_ask_filters_to_ask_only(self) -> None:
        # The auto-merge gate's primary use case: count just the
        # ask-user-routed items to know whether the gate can fire.
        events = [
            _classify_event(route="fix"),
            _classify_event(route="ask"),
            _classify_event(route="ask"),
            _classify_event(route="fix"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI, ["count-classifications", "--route", "ask"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_route_fix_filters_to_fix_only(self) -> None:
        # Symmetric coverage with --route ask. Used by retro tooling to
        # measure auto-fix volume per close cycle.
        events = [
            _classify_event(route="fix"),
            _classify_event(route="ask"),
            _classify_event(route="fix"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI, ["count-classifications", "--route", "fix"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_since_ts_excludes_earlier_events(self) -> None:
        # The auto-merge gate scopes "this close cycle" via CLOSE_START_TS
        # captured at preload time. Lexicographic ISO comparison: events
        # with ts strictly less than the bound are excluded; equal-or-
        # later are included.
        events = [
            _classify_event(route="ask", ts="2026-04-01T00:00:00+00:00"),
            _classify_event(route="ask", ts="2026-05-01T12:00:00+00:00"),
            _classify_event(route="ask", ts="2026-05-02T00:00:00+00:00"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            [
                "count-classifications",
                "--since-ts",
                "2026-05-01T00:00:00+00:00",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # April event excluded; May 1 + May 2 included → 2.
        self.assertEqual(result.stdout.strip(), "2")

    def test_category_filters_to_matching_only(self) -> None:
        # Per concern 28f5e1b919d6: free-close auto-merge needs a way to
        # block when ANY design_decision finding was classified, even if
        # routed to fix. The --category filter exposes that count.
        events = [
            _classify_event(route="ask", category="design_decision"),
            _classify_event(route="fix", category="lint"),
            _classify_event(route="fix", category="lint"),
            _classify_event(route="ask", category="design_decision"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--category", "design_decision"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_category_no_match_returns_zero(self) -> None:
        # When no events carry the requested category, count is 0 — the
        # absent-→-zero semantics auto-merge gates rely on.
        events = [
            _classify_event(route="fix", category="lint"),
            _classify_event(route="fix", category="test_failure"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--category", "design_decision"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_combined_category_and_since_ts(self) -> None:
        # Auto-merge gate's full-power invocation: count design_decision
        # findings only within this close cycle, regardless of route.
        events = [
            _classify_event(
                route="fix",
                category="design_decision",
                ts="2026-04-01T00:00:00+00:00",
            ),
            _classify_event(
                route="ask",
                category="design_decision",
                ts="2026-05-01T12:00:00+00:00",
            ),
            _classify_event(
                route="ask",
                category="lint",
                ts="2026-05-01T12:00:00+00:00",
            ),
            _classify_event(
                route="ask",
                category="design_decision",
                ts="2026-05-02T00:00:00+00:00",
            ),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            [
                "count-classifications",
                "--category",
                "design_decision",
                "--since-ts",
                "2026-05-01T00:00:00+00:00",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # 2 design_decision events on/after May 1 (May 1 ask + May 2 ask).
        self.assertEqual(result.stdout.strip(), "2")

    def test_cycle_id_filters_to_matching_only(self) -> None:
        # Per concern 1cf66a58205d: since-ts is time-scoped, not
        # cycle-scoped — concurrent close on another teammate worktree
        # could leak classifications into the gate's count. close_cycle_id
        # is the strict scoper; this filter exposes it.
        events = [
            _classify_event(route="ask", close_cycle_id="aaaa11111111"),
            _classify_event(route="ask", close_cycle_id="bbbb22222222"),
            _classify_event(route="ask", close_cycle_id="aaaa11111111"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_cycle_id_counts_events_without_metadata_key(self) -> None:
        # An event with NO metadata.close_cycle_id belongs to no cycle and
        # must still be counted when scoped — only an event tagged with a
        # DIFFERENT cycle id is excluded. This is what the story/free
        # auto-merge override actually gates on: an untagged route=ask
        # classify must not be silently dropped from ASK_COUNT.
        events = [
            _classify_event(route="ask"),  # no close_cycle_id
            _classify_event(route="ask", close_cycle_id="aaaa11111111"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_untagged_ask_classify_counted_when_scoped_to_cycle(self) -> None:
        # The real merge-past-blocker this story fixes: an untagged
        # route=ask concern_classify event must be counted, not invisible.
        events = [_classify_event(route="ask")]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--route", "ask", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_differently_tagged_classify_still_excluded(self) -> None:
        # Isolation guard: a classify event tagged with a DIFFERENT
        # close_cycle_id must still be excluded from a scoped count.
        events = [_classify_event(route="ask", close_cycle_id="bbbb22222222")]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            ["count-classifications", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_combined_route_and_since_ts(self) -> None:
        # Realistic auto-merge gate invocation: count just the ask-routed
        # classifications since the close cycle started.
        events = [
            _classify_event(route="fix", ts="2026-05-01T12:00:00+00:00"),
            _classify_event(route="ask", ts="2026-04-01T00:00:00+00:00"),
            _classify_event(route="ask", ts="2026-05-01T12:00:00+00:00"),
            _classify_event(route="ask", ts="2026-05-02T00:00:00+00:00"),
        ]
        write_events(self.events_file, events)
        result = run_cli(
            _CLI,
            [
                "count-classifications",
                "--route",
                "ask",
                "--since-ts",
                "2026-05-01T00:00:00+00:00",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Only the two ask events on/after May 1.
        self.assertEqual(result.stdout.strip(), "2")

    def test_malformed_json_lines_counted_as_potential_concern(self) -> None:
        # The event log is append-only with atomic writes, but a
        # truncated write or hand-edit could leave a malformed line. A
        # corrupt line could be hiding a real ask-routed classification,
        # so the CLI counts it (fail closed) rather than skipping it.
        good = _classify_event(route="ask")
        self.events_file.write_text(
            json.dumps(good) + "\n" + "{not valid json\n" + json.dumps(good) + "\n"
        )
        result = run_cli(
            _CLI, ["count-classifications", "--route", "ask"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "3")
        self.assertIn("fail closed", result.stderr)
        self.assertIn("unparseable", result.stderr)


if __name__ == "__main__":
    unittest.main()
