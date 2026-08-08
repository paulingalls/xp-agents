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
from event_metadata import METADATA_KEY_CWD, METADATA_KEY_TEST_FAILED
from event_schema import EVENT_TYPE_CONCERN

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

    def test_unparseable_run_writes_no_concern(self):
        concerns = self._run("python3 probe.py --arm jest", _LABEL_WITH_A_COUNT)
        self.assertEqual(concerns, [])


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
        concerns = self._run("pytest tests/", "3 passed, 2 failed in 1.2s", cwd=None)
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
