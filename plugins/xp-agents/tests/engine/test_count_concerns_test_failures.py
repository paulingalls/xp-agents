#!/usr/bin/env python3
"""`count-concerns --cycle-id` and a concurrent teammate's TDD red step.

Split from `test_smm_cli_count_concerns.py` (640 lines). Concern f995656dba80: a
sibling teammate's "Test failures detected" concern is untagged (no
close_cycle_id) and transient (it auto-resolves on a green run), so it must not
leak into another story's SCOPED close-gate count — while an ordinary untagged
high-severity concern still must.

The discriminator is narrow and easy to over-apply, which is why these group
together rather than sitting among the plain severity filters: a reviewer concern
that merely mentions test wording is NOT transient, and neither is one tagged
with this cycle.

story-008 is changing smm_count.py's behaviour concurrently. New cases about
transient test-failure exclusion belong here; cases about plain severity/cycle
filters belong in test_smm_cli_count_concerns.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _count_concerns_fixtures import _CLI, _concern
from concerns import TEST_COMMAND_FAILED_PREFIX, TEST_FAILURES_PREFIX
from conftest import _SMMTestCase, make_event, run_cli, write_events
from event_metadata import CONCERN_ACTION_TRANSIENT_TEST
from event_schema import EVENT_TYPE_STATUS


class TestTransientTestFailuresWhenScoped(_SMMTestCase):
    """Transient test-failure concerns and the scoped close gate."""

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
