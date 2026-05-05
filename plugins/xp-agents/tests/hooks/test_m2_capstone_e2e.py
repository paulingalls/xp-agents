#!/usr/bin/env python3
"""Capstone E2E for the M2 deterministic-event-emission vocabulary.

Drives the full producer → consumer → retro-digest pipeline against a fresh
SMM_DIR, asserting that every M2 lifecycle moment carries metadata.action +
its structured companion fields, and that retro counters increment via the
action path with no regex-fallback double-counting.

Sources of truth this capstone pins:
  - post_tool_use.py emits action=file_write + metadata.files
  - bash_post_tool.py emits action=test_run_complete + framework + counts
  - bash_post_tool.py emits action=commit_success on type=commit events
  - bash_failure.py emits action=bash_failed + exit_code
  - retro_metrics + honesty_signals consume those actions to drive counters
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import bash_post_tool
import honesty_signals
import post_tool_use
import retro_metrics
from _commit_helpers import patch_commits
from conftest import (
    _HookTestCase,
    _make_bash_failure_input,
    _make_bash_input,
    _make_write_input,
)
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_STATUS, event_action


class TestM2CapstoneActionVocabulary(_HookTestCase):
    """Cross-cutting assertions on the M2 action vocabulary end-to-end."""

    def _statuses(self, action: str) -> list[dict]:
        return [
            e
            for e in _common.read_events_raw(self.smm_dir)
            if e.get("type") == EVENT_TYPE_STATUS and event_action(e) == action
        ]

    def _commits(self) -> list[dict]:
        events = _common.read_events_raw(self.smm_dir)
        return events_of_type(events, EVENT_TYPE_COMMIT)

    def test_post_tool_use_emits_file_write_action(self):
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )
        emitted = self._statuses("file_write")
        self.assertEqual(len(emitted), 1)
        metadata = emitted[0].get("metadata") or {}
        self.assertEqual(metadata.get("files"), ["/tmp/src/app.ts"])

    def test_bash_pass_emits_test_run_complete(self):
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 5 passed in 0.4s =====",
            ),
            smm_dir=self.smm_dir,
        )
        emitted = self._statuses("test_run_complete")
        self.assertEqual(len(emitted), 1)
        metadata = emitted[0].get("metadata") or {}
        self.assertTrue(metadata.get("test_passed"))
        self.assertEqual(metadata.get("test_count"), 5)
        self.assertEqual(metadata.get("framework"), "pytest")

    def test_git_commit_emits_commit_success(self):
        with patch_commits(files=["scripts/foo.py"], body="Add foo"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add foo'",
                    stdout="[main abc1234] Add foo\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        commits = self._commits()
        self.assertEqual(len(commits), 1)
        metadata = commits[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "commit_success")
        self.assertIn("commit_hash", metadata)

    def test_bash_failure_emits_bash_failed(self):
        bash_failure.run(
            _make_bash_failure_input(
                command="pytest",
                error="Command failed with status 1",
                exit_code=1,
            ),
            smm_dir=self.smm_dir,
        )
        emitted = self._statuses("bash_failed")
        self.assertEqual(len(emitted), 1)
        metadata = emitted[0].get("metadata") or {}
        self.assertEqual(metadata.get("exit_code"), 1)


class TestM2CapstonePipelineRoundTrip(_HookTestCase):
    """The full producer → consumer round-trip: drive Write → pytest pass →
    git commit → bash failure as a sequence and assert the retro digest counts
    each lifecycle moment exactly once via the action path."""

    def test_full_pipeline_drives_action_path_only(self):
        # 1. Write — file_write producer.
        post_tool_use.run(
            _make_write_input(tool_response={"success": True}),
            smm_dir=self.smm_dir,
        )

        # 2. Passing pytest — test_run_complete producer.
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 3 passed in 0.2s =====",
            ),
            smm_dir=self.smm_dir,
        )

        # 3. Git commit — commit_success producer (on type=commit event).
        with patch_commits(files=["scripts/foo.py"], body="Wire it up"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Wire it up'",
                    stdout="[main abc1234] Wire it up\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

        # 4. Bash failure — bash_failed producer.
        bash_failure.run(
            _make_bash_failure_input(
                command="pytest",
                error="Command failed with status 1",
                exit_code=1,
            ),
            smm_dir=self.smm_dir,
        )

        events = _common.read_events_raw(self.smm_dir)
        status_summary = retro_metrics._classify_lifecycle_events(events)

        # Counters increment via the action path. Each lifecycle moment counts
        # exactly once — the regex fallback would only fire if action were
        # absent, so equality (not just non-zero) locks the no-double-count
        # invariant the doctrine requires.
        self.assertEqual(status_summary["file_writes"], 1)
        self.assertEqual(status_summary["test_runs"], 1)
        self.assertEqual(status_summary["commits"], 1)

        # Honesty signals reads metadata.files[0], not parsed content.
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["code_file_writes"], 1)


if __name__ == "__main__":
    unittest.main()
