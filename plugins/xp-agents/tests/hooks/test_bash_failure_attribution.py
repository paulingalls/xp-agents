#!/usr/bin/env python3
"""Run attribution on bash_failure's test-failure concern.

story-002. `bash_post_tool` records a run it PARSED; this hook records one it
only knows exited non-zero, and it often has no counts at all. Both must stamp
the same keys or a scoped run and a full-suite run keep rendering identically
at kickoff — but this producer must stamp FEWER of them, honestly.

Specifically: no total, ever. `parsed_failed_count` opts into
`allow_scan_fallback`, which reaches `result_counts.two_counts` — two
INDEPENDENT last-match scans whose sum can pair numbers from unrelated lines.
A denominator built from that would be plausible fiction on exactly the path
this story exists to keep honest.

Its own file rather than test_bash_failure.py (395 lines) because these cases
would push that file across the 450 band floor.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
from concerns import TEST_COMMAND_FAILED_PREFIX, TEST_FAILURES_PREFIX
from conftest import _HookTestCase, _make_bash_failure_input
from event_helpers import events_of_type
from event_metadata import (
    METADATA_KEY_CWD,
    METADATA_KEY_TEST_COUNT,
    METADATA_KEY_TEST_FAILED,
)
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

_WATERMARK_ID = "test-bash-failure-attribution"

# Corroborates the non-zero exit with real counts — parsed_failed_count returns 2.
_PARSED = "collected 5 items\n\n3 passed, 2 failed in 1.2s\n"
# A genuine failing run whose output the parser cannot read at all.
_UNPARSEABLE = "Traceback (most recent call last):\nImportError: no module named x\n"


class _AttributionTestCase(_HookTestCase):
    def _concerns(self, command: str, error: str, **overrides) -> list:
        inp = _make_bash_failure_input(command=command, error=error, **overrides)
        bash_failure.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return events_of_type(events, EVENT_TYPE_CONCERN)

    def _events(self) -> list:
        return _common.read_events_locked(self.smm_dir, _WATERMARK_ID)


class TestCorroboratedCount(_AttributionTestCase):
    """A non-zero exit the payload backs with real counts."""

    def test_concern_carries_cwd_and_failed_count(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            concerns_ = self._concerns(
                "pytest tests/", _PARSED, cwd="/Users/dev/wt/story-002"
            )
        self.assertEqual(len(concerns_), 1)
        metadata = concerns_[0]["metadata"]
        self.assertEqual(metadata[METADATA_KEY_CWD], "~/wt/story-002")
        self.assertEqual(metadata[METADATA_KEY_TEST_FAILED], 2)

    def test_concern_records_no_total(self):
        # The scan-fallback path cannot produce an honest denominator.
        concerns_ = self._concerns("pytest tests/", _PARSED, cwd="/tmp/proj")
        self.assertNotIn(METADATA_KEY_TEST_COUNT, concerns_[0]["metadata"])

    def test_content_prefix_unchanged(self):
        concerns_ = self._concerns("pytest tests/", _PARSED, cwd="/tmp/proj")
        self.assertTrue(concerns_[0]["content"].startswith(TEST_FAILURES_PREFIX))


class TestNoParseableCount(_AttributionTestCase):
    """The path this story exists for: a real failure with nothing to count."""

    def test_checkout_present_and_every_count_key_absent(self):
        concerns_ = self._concerns("pytest tests/", _UNPARSEABLE, cwd="/tmp/proj")
        self.assertEqual(len(concerns_), 1)
        metadata = concerns_[0]["metadata"]
        self.assertEqual(metadata[METADATA_KEY_CWD], "/tmp/proj")
        self.assertNotIn(METADATA_KEY_TEST_FAILED, metadata)
        self.assertNotIn(METADATA_KEY_TEST_COUNT, metadata)

    def test_content_prefix_unchanged(self):
        concerns_ = self._concerns("pytest tests/", _UNPARSEABLE, cwd="/tmp/proj")
        self.assertTrue(
            concerns_[0]["content"].startswith(TEST_COMMAND_FAILED_PREFIX),
            concerns_[0]["content"],
        )


class TestDegradesRatherThanFabricates(_AttributionTestCase):
    def test_absent_cwd_omits_the_key(self):
        # _make_bash_failure_input carries no cwd unless asked; the real
        # payload always does (hooks reference lists it as a common field),
        # but the producer must not invent one when it is missing.
        concerns_ = self._concerns("pytest tests/", _PARSED)
        self.assertNotIn(METADATA_KEY_CWD, concerns_[0]["metadata"])
        self.assertEqual(concerns_[0]["metadata"][METADATA_KEY_TEST_FAILED], 2)

    def test_unattributable_command_still_records_status_and_no_concern(self):
        # `grep -rn pytest src/` exiting 1 on no-match names a runner but did
        # not run one. Unchanged behavior — attribution must not widen it.
        concerns_ = self._concerns("grep -rn pytest src/", "exit 1", cwd="/tmp/proj")
        self.assertEqual(concerns_, [])
        self.assertEqual(len(events_of_type(self._events(), EVENT_TYPE_STATUS)), 1)


if __name__ == "__main__":
    unittest.main()
