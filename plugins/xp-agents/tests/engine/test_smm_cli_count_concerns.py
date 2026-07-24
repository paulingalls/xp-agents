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
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _close_fixtures import _quality_meta, _security_meta
from concerns import TEST_COMMAND_FAILED_PREFIX, TEST_FAILURES_PREFIX
from conftest import _SMMTestCase, make_event, run_cli, write_events
from event_metadata import CONCERN_ACTION_TRANSIENT_TEST
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

    def test_cycle_id_excludes_only_differently_tagged_events(self) -> None:
        # SMM is shared across worktrees — concurrent close-cycles must not
        # leak in. But an event with NO close_cycle_id belongs to no cycle
        # and must still be counted when scoped — only an event tagged with
        # a DIFFERENT cycle id is excluded. A reviewer's untagged concern
        # must not become invisible to the gate.
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
        self.assertEqual(result.stdout.strip(), "3")

    def test_untagged_high_concern_counted_when_scoped_to_cycle(self) -> None:
        # A reviewer's severity=high concern filed WITHOUT close_cycle_id
        # must not be invisible to a scoped count — this is the fail-OPEN
        # bug the fix closes.
        write_events(self.events_file, [_concern("high", metadata={})])
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_differently_tagged_concern_still_excluded(self) -> None:
        # Isolation guard: a concern tagged with a DIFFERENT close_cycle_id
        # must still be excluded from a scoped count.
        write_events(
            self.events_file,
            [_concern("high", metadata={"close_cycle_id": "bbbb22222222"})],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_resolved_via_metadata_resolves_not_counted(self) -> None:
        # A severity=high concern closed via metadata.resolves is no longer
        # open — count-concerns must count OPEN concerns, not concerns filed.
        concern = _concern("high")
        closer = make_event(
            EVENT_TYPE_STATUS,
            working_on=[],
            metadata={"action": "qr_complete", "resolves": [concern["id"]]},
        )
        write_events(self.events_file, [concern, closer])
        result = run_cli(_CLI, ["count-concerns", "--severity", "high"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_resolved_via_weak_references_cascade_not_counted(self) -> None:
        # A concern resolved indirectly via the WEAK references cascade
        # (its `references` reach an already-resolved event) must also be
        # excluded — not just direct metadata.resolves closures.
        root = _concern("high")
        closer = make_event(
            EVENT_TYPE_STATUS,
            working_on=[],
            metadata={"action": "qr_complete", "resolves": [root["id"]]},
        )
        cascaded = _concern("high", references=[root["id"]])
        write_events(self.events_file, [root, closer, cascaded])
        result = run_cli(_CLI, ["count-concerns", "--severity", "high"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_untagged_and_resolved_not_counted(self) -> None:
        # The untagged-fallthrough fix and the resolution filter compose:
        # an untagged concern that is ALSO resolved must still be excluded.
        concern = _concern("high", metadata={})
        closer = make_event(
            EVENT_TYPE_STATUS,
            working_on=[],
            metadata={"action": "qr_complete", "resolves": [concern["id"]]},
        )
        write_events(self.events_file, [concern, closer])
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_since_ts_still_bounds_untagged_concerns(self) -> None:
        # --since-ts remains a real bound on untagged concerns — an old
        # untagged concern from before this close cycle started must not
        # leak into a scoped-by-time count.
        write_events(
            self.events_file,
            [
                _concern(
                    "high", metadata={}, ts="2026-04-01T00:00:00+00:00"
                ),  # too old
                _concern(
                    "high", metadata={}, ts="2026-05-02T00:00:00+00:00"
                ),  # in window
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

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

    def test_malformed_line_counts_as_potential_concern(self) -> None:
        # A corrupt line could be hiding a high-severity concern — fail
        # closed by counting it, rather than fail-open by skipping it.
        valid = _concern("high")
        self.events_file.write_text(
            json.dumps(valid) + "\n" + "{not valid json}\n" + "\n"
        )
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")
        self.assertIn("fail closed", result.stderr)
        self.assertIn("unparseable", result.stderr)

    def test_corrupt_line_with_old_embedded_ts_excluded_when_scoped(self) -> None:
        # Concern a11e9132e5bc / debt 7e8219afe702: a corrupt line from
        # BEFORE this close cycle's window must not permanently force
        # every future --since-ts-scoped count non-zero. A raw "ts"
        # substring recoverable from the unparseable line and provably
        # older than --since-ts is positive evidence the line is out of
        # scope, so it must be excluded rather than added to the floor.
        valid = _concern("high", ts="2026-05-02T00:00:00+00:00")
        # truncated write — looks like an object, embeds an old ts
        corrupt_old = '{"ts": "2026-01-01T00:00:00+00:00", "type": "concern", "severi'
        self.events_file.write_text(json.dumps(valid) + "\n" + corrupt_old + "\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("provably out of scope", result.stderr)

    def test_corrupt_line_with_no_extractable_ts_still_counted(self) -> None:
        # Floor preserved: no ts substring is recoverable at all, so the
        # line must still count even though --since-ts is provided —
        # extraction only ever narrows the floor with positive evidence,
        # never loosens it for genuinely unscopable corruption.
        self.events_file.write_text("{completely garbled, no ts field}\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_with_recent_embedded_ts_still_counted(self) -> None:
        # A corrupt line whose embedded ts falls WITHIN (or after) the
        # scoped window must still count — the exclusion only fires on
        # provable out-of-window evidence, not merely because a ts was
        # found.
        corrupt_recent = '{"ts": "2026-05-02T00:00:00+00:00", "type": "conce'
        self.events_file.write_text(corrupt_recent + "\n")
        result = run_cli(
            _CLI,
            ["count-concerns", "--since-ts", "2026-05-01T00:00:00+00:00"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_corrupt_line_with_old_ts_still_counted_without_since_ts(self) -> None:
        # Without --since-ts there is no window to prove exclusion
        # against — the floor must hold unconditionally, matching the
        # pre-existing unscoped fail-closed behavior.
        corrupt_old = '{"ts": "2026-01-01T00:00:00+00:00", "type": "conce'
        self.events_file.write_text(corrupt_old + "\n")
        result = run_cli(_CLI, ["count-concerns"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        self.assertIn("fail closed", result.stderr)

    def test_untagged_transient_test_failure_excluded_when_scoped(self) -> None:
        # concern f995656dba80: a concurrent teammate's TDD red-step
        # "Test failures detected" concern is untagged (no close_cycle_id)
        # and transient (auto-resolves on a green run) — it must not leak
        # into a SIBLING's scoped close-gate count.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"action": CONCERN_ACTION_TRANSIENT_TEST},
                    content=f"{TEST_FAILURES_PREFIX}: 2 failed (pytest)",
                )
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_untagged_command_failed_concern_excluded_when_scoped(self) -> None:
        # bash_failure.py's no-parseable-count path emits a HIGH, untagged
        # "Test command failed (framework): ..." concern — the SAME transient
        # class (auto-resolves on green via TEST_CONCERN_RE), a DIFFERENT
        # producer shape than bash_post_tool's "Test failures detected". It
        # must also stay out of a sibling's scoped close-gate count.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"action": CONCERN_ACTION_TRANSIENT_TEST},
                    content=f"{TEST_COMMAND_FAILED_PREFIX} (pytest): ImportError",
                )
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_untagged_ordinary_high_concern_still_counted_when_scoped(self) -> None:
        # M4 preserved: the exclusion is narrow to the test-failure class,
        # not a blanket untagged-drop (the refuted Try 4782e7c41bdf).
        write_events(
            self.events_file,
            [_concern("high", metadata={}, content="Data loss: unbounded queue")],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_untagged_test_failure_still_counted_when_unscoped(self) -> None:
        # Without --cycle-id there is no close-gate to protect — the
        # general count keeps counting every open concern as before.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"action": CONCERN_ACTION_TRANSIENT_TEST},
                    content=f"{TEST_FAILURES_PREFIX}: 2 failed (pytest)",
                )
            ],
        )
        result = run_cli(_CLI, ["count-concerns", "--severity", "high"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_resolved_test_failure_already_excluded_with_and_without_cycle_id(
        self,
    ) -> None:
        # Regression pin: a resolved test-failure concern is already
        # excluded by the existing resolved_ids filter, independent of
        # this story's new exclusion.
        concern = _concern(
            "high",
            metadata={},
            content=f"{TEST_FAILURES_PREFIX}: 1 failed (pytest)",
        )
        closer = make_event(
            EVENT_TYPE_STATUS,
            working_on=[],
            metadata={"action": "qr_complete", "resolves": [concern["id"]]},
        )
        write_events(self.events_file, [concern, closer])
        result_scoped = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        result_unscoped = run_cli(
            _CLI, ["count-concerns", "--severity", "high"], self.smm_dir
        )
        self.assertEqual(result_scoped.returncode, 0, result_scoped.stderr)
        self.assertEqual(result_unscoped.returncode, 0, result_unscoped.stderr)
        self.assertEqual(result_scoped.stdout.strip(), "0")
        self.assertEqual(result_unscoped.stdout.strip(), "0")

    def test_untagged_reviewer_concern_with_test_wording_still_counted(self) -> None:
        # agents/xp-close-reviewer.md tells reviewers the close_cycle_id is
        # OPTIONAL: "an untagged concern is counted, never dropped". So a
        # reviewer Block worded "Test command failed on a clean checkout" and
        # filed WITHOUT the tag must still count — otherwise the shipped prose
        # is false and the abort gate silently drops a real block.
        #
        # Content cannot distinguish it from the transient class, so the
        # exclusion keys on the producer marker and fails CLOSED: an event
        # carrying some OTHER action, or authored by an agent (no action at
        # all beyond what it set), is counted.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"kind": "quality"},
                    content=f"{TEST_COMMAND_FAILED_PREFIX} on a clean checkout",
                )
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "1",
            "an untagged reviewer Block must count even when its wording "
            "matches the transient class — the marker, not the text, decides",
        )

    def test_marked_transient_concern_excluded_when_scoped(self) -> None:
        # The positive half: a concern carrying the producer marker IS the
        # transient class and stays excluded, so story-007's original fix
        # (concern f995656dba80) still holds.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"action": CONCERN_ACTION_TRANSIENT_TEST},
                    content="Anything at all — the marker decides, not this text",
                )
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")

    def test_test_failure_wording_tagged_with_this_cycle_still_counted(self) -> None:
        # The transient class the exclusion targets is UNTAGGED by definition
        # (bash_post_tool/bash_failure never set close_cycle_id). A concern
        # explicitly tagged with THIS cycle came from the close reviewer, so it
        # must count even when its wording happens to match TEST_CONCERN_RE —
        # otherwise a genuine cycle-tagged HIGH block ("test command failed on
        # a clean checkout") is silently subtracted from the number driving the
        # auto-merge conditions, and the story auto-merges over it.
        cycle = "aaaa11111111"
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"close_cycle_id": cycle},
                    content="Real reviewer finding: null deref in merge path",
                ),
                _concern(
                    "high",
                    metadata={"close_cycle_id": cycle},
                    content=f"{TEST_COMMAND_FAILED_PREFIX} on a clean checkout",
                ),
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", cycle],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_test_failure_tagged_with_different_cycle_id_still_excluded(self) -> None:
        # A test-failure concern tagged with a DIFFERENT close_cycle_id is
        # excluded by both the cycle-id filter AND the new transient-class
        # exclusion — confirm it stays excluded either way.
        write_events(
            self.events_file,
            [
                _concern(
                    "high",
                    metadata={"close_cycle_id": "bbbb22222222"},
                    content=f"{TEST_FAILURES_PREFIX}: 3 failed (pytest)",
                )
            ],
        )
        result = run_cli(
            _CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", "aaaa11111111"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
