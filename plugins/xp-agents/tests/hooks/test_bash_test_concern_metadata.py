#!/usr/bin/env python3
"""Run-identifying metadata on the bash_post_tool test-failure concern.

story-001: a 1-test scoped run, a `docker compose exec ... pytest`, a
teammate's worktree run and a 508-test suite all surfaced identically at
kickoff — the concern that carries forward carried no cwd and no counts.
This pins the producer leg: `metadata.cwd` ($HOME collapsed to `~`, omitted
when the payload carries none) and `metadata.test_failed`/`test_count`/
`test_errors`, mirroring the STATUS event's own spellings.
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
import bash_post_tool
from _commit_helpers import patch_commits
from concerns import TEST_FAILURES_PREFIX
from conftest import _HookTestCase, _make_bash_input
from event_helpers import events_of_type
from event_metadata import (
    CONCERN_ACTION_TRANSIENT_TEST,
    METADATA_KEY_CWD,
    METADATA_KEY_TEST_FAILED,
)
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

_WATERMARK_ID = "test-bash-test-concern-metadata"

# The live no-result shape from test_bash_no_result.py: a runner mentioned as
# an argument, with a count only in a label — PARSER_STATUS_FAILED, failed=0.
_LABEL_WITH_A_COUNT = "probe: arm jest, fixture 'must report 3 failed rows'\ndone\n"


class _ConcernMetadataTestCase(_HookTestCase):
    def _run(self, command: str, stdout: str, cwd: str | None = "/tmp/proj") -> list:
        inp = _make_bash_input(command=command, stdout=stdout)
        if cwd is None:
            del inp["cwd"]
        else:
            inp["cwd"] = cwd
        with patch_commits(files=[], body=""):
            bash_post_tool.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return events_of_type(events, EVENT_TYPE_CONCERN)


class TestConcernCounts(_ConcernMetadataTestCase):
    def test_concern_carries_failed_and_total_counts(self):
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertEqual(len(concerns), 1)
        metadata = concerns[0]["metadata"]
        self.assertEqual(metadata[METADATA_KEY_TEST_FAILED], 2)
        self.assertEqual(metadata["test_count"], 5)

    def test_concern_omits_test_errors_when_none_observed(self):
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertNotIn("test_errors", concerns[0]["metadata"])

    def test_concern_includes_test_errors_when_present(self):
        concerns = self._run("pytest tests/", "3 passed, 2 failed, 1 error in 1.2s")
        self.assertEqual(concerns[0]["metadata"]["test_errors"], 1)

    def test_content_prefix_unchanged(self):
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertTrue(concerns[0]["content"].startswith(TEST_FAILURES_PREFIX))

    def test_action_discriminator_survives_the_attribution_block(self):
        # The attribution keys are SPREAD in after "action", so a key named
        # "action" leaking out of the builder would silently replace the
        # discriminator every consumer of this concern routes on. bash_failure
        # has the same pin (test_bash_failure.py); this is the parsed leg.
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertEqual(
            concerns[0]["metadata"]["action"], CONCERN_ACTION_TRANSIENT_TEST
        )

    def test_unparseable_run_writes_no_concern(self):
        concerns = self._run("python3 probe.py --arm jest", _LABEL_WITH_A_COUNT)
        self.assertEqual(concerns, [])


class TestTotalOnlyWhenTrustworthy(_ConcernMetadataTestCase):
    """A denominator is recorded only when the passes were actually seen.

    `result_counts.two_counts` returns `p or 0`, which collapses "0 passed"
    into "passed not observed". Summing that into a total asserts a
    proportion the parser never had evidence for: a 500-test playwright run
    whose pass line is absent from the captured output parses as
    passed=0/failed=2 and would render `[2/2 failed]` — the whole suite red.

    So when `passed` is 0 alongside real failures, the total is omitted and
    the concern degrades to the count-alone render story-002 already ships.
    Same rule bash_failure follows for the same reason; this producer had
    been exempt from it by oversight.
    """

    def test_total_omitted_when_no_passes_were_observed(self):
        concerns = self._run(
            "npx playwright test",
            "Running 500 tests using 10 workers\n\n  2 failed\n    a.spec.ts:3:1\n",
        )
        self.assertEqual(len(concerns), 1)
        metadata = concerns[0]["metadata"]
        self.assertEqual(metadata[METADATA_KEY_TEST_FAILED], 2)
        self.assertNotIn(
            "test_count",
            metadata,
            "a 500-test run must not claim 2/2 — the parser never saw the passes",
        )

    def test_total_recorded_when_passes_were_observed(self):
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertEqual(concerns[0]["metadata"]["test_count"], 5)

    def _status_metadata(self, command: str, stdout: str) -> dict:
        inp = _make_bash_input(command=command, stdout=stdout)
        inp["cwd"] = "/tmp/proj"
        with patch_commits(files=[], body=""):
            bash_post_tool.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        return statuses[-1]["metadata"]

    def test_status_leg_omits_the_untrusted_total_too(self):
        # The sibling STATUS event carries the same METADATA_KEY_TEST_COUNT.
        # Sharing the spelling is not sharing the trust rule — fixing only the
        # concern would leave the same fabricated 2/2 one event over.
        metadata = self._status_metadata(
            "npx playwright test",
            "Running 500 tests using 10 workers\n\n  2 failed\n    a.spec.ts:3:1\n",
        )
        self.assertNotIn("test_count", metadata)

    def test_status_leg_keeps_the_total_when_passes_were_observed(self):
        metadata = self._status_metadata("pytest tests/", "3 passed, 2 failed in 1.2s")
        self.assertEqual(metadata["test_count"], 5)


class TestConcernCwdAttribution(_ConcernMetadataTestCase):
    def test_cwd_collapses_home_to_tilde(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            concerns = self._run(
                "pytest tests/",
                "3 passed, 2 failed in 1.2s",
                cwd="/Users/dev/worktree-story-001-x/repo",
            )
        self.assertEqual(
            concerns[0]["metadata"][METADATA_KEY_CWD],
            "~/worktree-story-001-x/repo",
        )

    def test_cwd_outside_home_stays_absolute(self):
        with patch.dict(os.environ, {"HOME": "/Users/dev"}):
            concerns = self._run(
                "pytest tests/",
                "3 passed, 2 failed in 1.2s",
                cwd="/tmp/container-mount",
            )
        self.assertEqual(
            concerns[0]["metadata"][METADATA_KEY_CWD], "/tmp/container-mount"
        )

    def test_cwd_omitted_when_payload_carries_none(self):
        # No cwd key on the payload also removes the `.` fallback the OTHER
        # branch (_working_tree_is_test_only) relies on, which would then
        # shell out against this real repo's actual working tree. Patched out
        # here since it is irrelevant to what this test is pinning: metadata
        # attribution, not tree-only detection.
        with patch("bash_post_tool._working_tree_is_test_only", return_value=False):
            concerns = self._run(
                "pytest tests/", "3 passed, 2 failed in 1.2s", cwd=None
            )
        self.assertEqual(len(concerns), 1)
        self.assertNotIn(METADATA_KEY_CWD, concerns[0]["metadata"])

    def test_command_never_recorded(self):
        """The most diagnostic field is deliberately excluded — a command
        line can carry a token, and this log renders back into prompts."""
        concerns = self._run(
            "pytest tests/ --token=SECRET123", "3 passed, 2 failed in 1.2s"
        )
        self.assertNotIn("command", concerns[0]["metadata"])
        self.assertNotIn("SECRET123", str(concerns[0]["metadata"]))


if __name__ == "__main__":
    unittest.main()
