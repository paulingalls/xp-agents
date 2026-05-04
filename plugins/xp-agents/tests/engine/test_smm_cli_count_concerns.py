#!/usr/bin/env python3
"""Tests for `smm_cli.py count-concerns`.

Counts type==concern events filtered by --severity, --cycle-id (matches
metadata.close_cycle_id), and --since-ts (lex ISO comparison). Used by
the shared close-pipeline Step 6 abort-default.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _close_fixtures import _quality_meta, _security_meta
from conftest import _SMMTestCase, make_event, run_cli, write_events
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"

# Distinct 12-hex cycle ids used by the realistic close-cycle fixture
# tests below — keeps them visually distinguishable when scanning the
# fixtures and matches the module-constant pattern in the e2e suite.
_CYCLE_SOLO = "ccccddddeeee"
_CYCLE_A = "aaaa00001111"
_CYCLE_B = "bbbb22223333"


def _concern(severity: str, **kwargs) -> dict:
    """Concern event factory keyed by severity. Other fields kwargs-overridable."""
    return make_event(EVENT_TYPE_CONCERN, severity=severity, files=[], **kwargs)


class TestCountConcerns(_SMMTestCase):
    def test_returns_zero_when_no_events_file(self) -> None:
        self.events_file.unlink()
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_returns_zero_when_no_concern_events(self) -> None:
        # Status events must not be counted — only type==concern.
        write_events(
            self.events_file,
            [
                make_event(
                    EVENT_TYPE_STATUS, working_on=[], metadata={"action": "qr_complete"}
                )
            ],
        )
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_counts_all_concerns_when_no_filters(self) -> None:
        write_events(
            self.events_file,
            [_concern("high"), _concern("medium"), _concern("low")],
        )
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "3")

    def test_severity_high_filters_to_high_only(self) -> None:
        # Step 6 abort-default's load-bearing case: count severity=high.
        write_events(
            self.events_file,
            [_concern("high"), _concern("medium"), _concern("high"), _concern("low")],
        )
        result = run_cli(_CLI, ["count-concerns", "--severity", "high"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_invalid_severity_rejected_by_choices(self) -> None:
        # Typo defense — silent zero on invalid severity would defeat
        # the security gate, so argparse choices= must reject up-front.
        write_events(self.events_file, [_concern("high")])
        result = run_cli(_CLI, ["count-concerns", "--severity", "High"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_cycle_id_filters_to_matching_close_cycle_only(self) -> None:
        # SMM is shared across worktrees — concurrent close-cycles must
        # not leak in. Events without close_cycle_id never match.
        write_events(
            self.events_file,
            [
                _concern("high", metadata={"close_cycle_id": "aaaa11111111"}),
                _concern("high", metadata={"close_cycle_id": "bbbb22222222"}),
                _concern("high", metadata={}),
                _concern("high", metadata={"close_cycle_id": "aaaa11111111"}),
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_since_ts_excludes_earlier_events(self) -> None:
        write_events(
            self.events_file,
            [
                _concern("high", ts="2026-04-01T00:00:00+00:00"),
                _concern("high", ts="2026-05-01T12:00:00+00:00"),
                _concern("high", ts="2026-05-02T00:00:00+00:00"),
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_combined_severity_cycle_id_and_since_ts(self) -> None:
        # The canonical close-skill invocation.
        write_events(
            self.events_file,
            [
                _concern(
                    "medium",
                    metadata={"close_cycle_id": "cycle1aaaaaa"},
                    ts="2026-05-01T12:00:00+00:00",
                ),  # wrong severity
                _concern(
                    "high",
                    metadata={"close_cycle_id": "cycle2bbbbbb"},
                    ts="2026-05-01T12:00:00+00:00",
                ),  # wrong cycle
                _concern(
                    "high",
                    metadata={"close_cycle_id": "cycle1aaaaaa"},
                    ts="2026-04-30T00:00:00+00:00",
                ),  # too old
                _concern(
                    "high",
                    metadata={"close_cycle_id": "cycle1aaaaaa"},
                    ts="2026-05-01T12:00:00+00:00",
                ),  # match
                _concern(
                    "high",
                    metadata={"close_cycle_id": "cycle1aaaaaa"},
                    ts="2026-05-02T00:00:00+00:00",
                ),  # match
            ],
        )
        result = run_cli(
            _CLI,
            [
                "count-concerns",
                "--severity",
                "high",
                "--cycle-id",
                "cycle1aaaaaa",
                "--since-ts",
                "2026-05-01T00:00:00+00:00",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_realistic_close_cycle_fixture_with_kind_security_and_quality(
        self,
    ) -> None:
        # Realistic shape regression guard for the sprint-055 class of
        # bug (concern 0825da9526de): close-reviewer's quality blocks
        # carry the full close_mode/source_branch/target_branch/
        # close_cycle_id metadata block, while Step 4.5 security blocks
        # carry kind=security alongside close_cycle_id. The Step 6
        # count-concerns query must include BOTH under one cycle-id —
        # `kind` is not a filter, only severity + close_cycle_id are.
        cycle = _CYCLE_SOLO
        write_events(
            self.events_file,
            [
                _concern("high", metadata=_quality_meta(cycle)),  # quality #1
                _concern("high", metadata=_quality_meta(cycle)),  # quality #2
                _concern("high", metadata=_security_meta(cycle)),  # kind=security
                _concern("medium", metadata=_security_meta(cycle)),  # medium: skipped
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", cycle],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "3",
            "count must include both kind=security AND quality blocks "
            "(no `kind`) when scoped to a single close_cycle_id",
        )

    def test_realistic_two_concurrent_cycles_isolated_by_cycle_id(self) -> None:
        # Two concurrent close-cycles in the same events.jsonl (e.g. two
        # teammate worktrees both running close skills against the
        # shared SMM). Filtering by cycle A must exclude every cycle B
        # event regardless of severity, kind, source/target branch, or
        # event ordering.
        write_events(
            self.events_file,
            [
                _concern("high", metadata=_quality_meta(_CYCLE_A)),
                _concern("high", metadata=_security_meta(_CYCLE_A)),
                # Cycle B noise — same severity, same kind shapes — must NOT leak.
                _concern(
                    "high",
                    metadata=_quality_meta(
                        _CYCLE_B, close_mode="free", source_branch="free-branch"
                    ),
                ),
                _concern("high", metadata=_security_meta(_CYCLE_B, close_mode="free")),
                _concern("high", metadata=_security_meta(_CYCLE_B, close_mode="free")),
            ],
        )
        result_a = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", _CYCLE_A],
            self.smm_dir,
        )
        result_b = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", _CYCLE_B],
            self.smm_dir,
        )
        self.assertEqual(result_a.returncode, 0, result_a.stderr)
        self.assertEqual(result_b.returncode, 0, result_b.stderr)
        self.assertEqual(result_a.stdout.strip(), "2")
        self.assertEqual(result_b.stdout.strip(), "3")

    def test_skips_malformed_lines(self) -> None:
        # parse_jsonl handles bad lines — pin contract at the CLI boundary.
        valid = _concern("high")
        self.events_file.write_text(
            json.dumps(valid) + "\n" + "{not valid json}\n" + "\n"
        )
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
