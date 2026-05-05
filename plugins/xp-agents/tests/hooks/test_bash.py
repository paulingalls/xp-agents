#!/usr/bin/env python3
"""Tests for bash_post_tool.py: commit events and test framework detection.

Probe status events are now emitted from pre_tool_bash (not post-commit).
Review cycle, green nudge, push warning, and QR linkage are in
test_bash_commit.py. Failure handling and compat tests are in test_bash_failure.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import commits
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)
from test_parsing import PARSER_STATUS_FAILED, PARSER_STATUS_PARSED, PARSER_STATUS_ZERO


class TestBashPostTool(_ProbeTestHelpers, _HookTestCase):
    def test_git_commit_records_commit_event(self):
        with patch_commits(files=["a", "b", "c"], body="Add auth"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add auth'",
                    stdout="[main abc123] Add auth\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commits_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commits_ev), 1)
        self.assertIn("Add auth", commits_ev[0]["content"])
        self.assertEqual(commits_ev[0]["files"], ["a", "b", "c"])
        self.assertEqual(commits_ev[0]["metadata"]["commit_hash"], "abc123")

    def test_git_commit_captures_resolves_trailer(self):
        """Resolves-Event trailer populates metadata.resolves on the commit event."""
        body = (
            "Fix the thing\n\nRationale.\n\n"
            "Resolves-Event: 4eb35ddcd24e, a55290ae79b9\n"
            "Co-Authored-By: Claude <x@y>"
        )
        with patch_commits(files=["a.py"], body=body):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix the thing'",
                    stdout="[main abc123] Fix the thing\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)[0]
        self.assertEqual(
            commit_ev["metadata"]["resolves"],
            ["4eb35ddcd24e", "a55290ae79b9"],
        )

    def test_git_commit_no_resolves_trailer_omits_key(self):
        """Absent trailer must not add a resolves key to metadata."""
        body = "Fix the thing\n\nNo trailer here."
        with patch_commits(files=["a.py"], body=body):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix'",
                    stdout="[main abc123] Fix\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)[0]
        self.assertNotIn("resolves", commit_ev["metadata"])

    def test_git_commit_strips_co_author_trailer(self):
        body = (
            "Fix the bug\n\nDetailed explanation.\n\nCo-Authored-By: Someone <x@y.com>"
        )
        with patch_commits(files=["a.py"], body=body):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix the bug'",
                    stdout="[main abc123] Fix the bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commits_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commits_ev), 1)
        self.assertNotIn("Co-Authored-By", commits_ev[0]["content"])
        self.assertIn("Detailed explanation", commits_ev[0]["content"])

    def test_git_commit_small_no_concern(self):
        with patch("commits.get_committed_files", return_value=["a", "b", "c"]):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main abc123] Fix bug\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0)

    def test_git_commit_large_appends_concern(self):
        with patch(
            "commits.get_committed_files",
            return_value=[f"f{i}" for i in range(12)],
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Big change'",
                    stdout="[main abc123] Big change\n 12 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("12 files" in c["content"] for c in concerns))

    def test_commit_code_files_has_code_commit_metadata(self):
        """Commit event has metadata.code_commit=True when code files present."""
        with patch_commits(
            files=["src/app.py", "tests/test_app.py"],
            body="Add feature",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main abc123] Add feature\n 2 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(committed), 1)
        self.assertTrue(committed[0].get("metadata", {}).get("code_commit"))

    def test_commit_no_code_files_has_code_commit_false(self):
        """Commit event has metadata.code_commit=False for docs-only commits."""
        with patch_commits(
            files=["README.md", "docs/guide.md"],
            body="Update docs",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Update docs'",
                    stdout="[main abc123] Update docs\n 2 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(committed), 1)
        self.assertFalse(committed[0].get("metadata", {}).get("code_commit"))

    def test_commit_with_sprint_has_sprint_id_metadata(self):
        """Commit event has metadata.sprint_id when sprint.json exists."""
        from conftest import _s, _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Add auth", "in-progress")],
                sprint_id="sprint-042",
            )
        )
        with patch_commits(files=["a.py"], body="feat"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'feat'",
                    stdout="[main abc123] feat\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(committed), 1)
        self.assertEqual(
            committed[0].get("metadata", {}).get("sprint_id"),
            "sprint-042",
        )

    def test_pytest_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("5 passed" in s["content"] for s in statuses))

    def test_pytest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 3 passed, 2 failed in 1.2s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            _make_bash_input(command="npx jest", stdout="Tests:  5 passed, 5 total"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertTrue(len(statuses) >= 1)

    def test_jest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="npx jest",
                stdout="Tests:  2 failed, 3 passed, 5 total",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="ok  \tgithub.com/user/pkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertTrue(len(statuses) >= 1)

    def test_go_test_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="--- FAIL: TestSomething (0.00s)\nFAIL\tpkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            _make_bash_input(command="ls -la", stdout="total 0"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips_non_commit_bash(self):
        # Commit-recording is exempt from the is_xp_agent skip (see
        # TestCommitRecordingDespiteXpAgentType in test_bash_commit.py).
        # Non-commit Bash from an xp-agent still skips.
        bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 1.2s =====",
                agent_type="xp-housekeeper",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        bash_post_tool.run(
            _make_bash_input(command="git commit -m 'x'", stdout="[main a] x"),
            smm_dir=fake_dir,
        )

    def test_git_commit_parse_message(self):
        response = "[main abc123] Fix login bug\n 1 file changed"
        self.assertEqual(commits.parse_commit_message(response), "Fix login bug")

    def _run_commit(
        self,
        body: str,
        committed_files: list[str],
        commit_msg: str,
        commit_hash: str | None = "abc123",
    ):
        """Run bash_post_tool with mocked git metadata and return the value."""
        with patch_commits(files=committed_files, body=body, head_sha=commit_hash):
            return bash_post_tool.run(
                _make_bash_input(
                    command=f"git commit -m '{commit_msg}'",
                    stdout=f"[main abc123] {commit_msg}\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )

    def _run_auth_fix(self, body: str = "Fix auth\n\nNo trailer.", **kw):
        """Helper: run a commit touching scripts/auth.py."""
        return self._run_commit(
            body=body,
            committed_files=["scripts/auth.py"],
            commit_msg="Fix auth",
            **kw,
        )

    def test_commit_no_nudge_on_file_overlap(self):
        """Post-commit returns no nudge text on file overlap (moved to pre-commit)."""
        self._seed_auth_concern()
        self._seed_qr_status()
        result = self._run_auth_fix(body="Fix auth\n\nNo trailer here.")
        self.assertIsNone(result)

    def _seed_qr_status(self) -> None:
        """Seed a quality-review status event to suppress QR-linkage warning."""
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_STATUS,
                content="Quality review complete. No issues.",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        )

    def test_commit_no_nudge_when_concern_resolved_by_trailer(self):
        """Resolves-Event trailer covering the matching concern -> no nudge."""
        cid = self._seed_auth_concern()
        self._seed_qr_status()
        result = self._run_auth_fix(body=f"Fix auth\n\nResolves-Event: {cid}")
        self.assertIsNone(result)

    def test_commit_no_nudge_when_no_file_overlap(self):
        """Concern's files don't intersect commit files -> no nudge."""
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Other bug", files=["scripts/foo.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        self._seed_qr_status()
        result = self._run_commit(
            body="Update README\n\nNo trailer.",
            committed_files=["README.md"],
            commit_msg="Update README",
        )
        self.assertIsNone(result)

    def test_post_commit_no_nudge_text(self):
        """Post-commit no longer returns nudge text (moved to pre-commit)."""
        self._seed_auth_concern()
        self._seed_qr_status()
        result = self._run_auth_fix()
        self.assertIsNone(result)

    def test_post_commit_no_probe_event(self):
        """Post-commit no longer emits probe events (moved to pre-commit)."""
        self._seed_auth_concern()
        self._run_auth_fix()
        self.assertEqual(self._probes(), [])


class TestM2TestRunActions(_HookTestCase):
    """sprint-042 M2: bash_post_tool emits metadata.action=test_run_complete
    with structured test_passed/test_count/framework fields. Content stays
    as the legacy 'Tests: ...' digest for the dual-emit window."""

    def _status(self, command: str, stdout: str) -> dict:
        bash_post_tool.run(
            _make_bash_input(command=command, stdout=stdout),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 1, f"expected 1 status, got {len(statuses)}")
        return statuses[0]

    def test_passing_pytest_carries_structured_metadata(self):
        status = self._status("pytest", "===== 3 passed in 0.3s =====")
        metadata = status.get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_TEST_RUN_COMPLETE)
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_PARSED)
        self.assertTrue(metadata.get("test_passed"))
        self.assertEqual(metadata.get("test_count"), 3)
        self.assertEqual(metadata.get("framework"), "pytest")
        # Content keeps the legacy digest.
        self.assertIn("3 passed", status["content"])

    def test_failing_pytest_carries_test_passed_false(self):
        status = self._status("pytest", "===== 1 passed, 2 failed in 0.5s =====")
        metadata = status.get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_TEST_RUN_COMPLETE)
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_PARSED)
        self.assertFalse(metadata.get("test_passed"))
        self.assertEqual(metadata.get("test_count"), 3)
        self.assertEqual(metadata.get("framework"), "pytest")

    def test_garbled_emits_parser_failed_status(self):
        status = self._status("pytest", "garbled output with no counts")
        metadata = status.get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_TEST_RUN_COMPLETE)
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_FAILED)
        self.assertNotIn("test_count", metadata)
        self.assertNotIn("test_passed", metadata)
        self.assertEqual(metadata.get("framework"), "pytest")

    def test_zero_tests_emits_zero_status_with_count_zero(self):
        status = self._status("pytest", "===== no tests ran in 0.1s =====")
        metadata = status.get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_TEST_RUN_COMPLETE)
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_ZERO)
        self.assertEqual(metadata.get("test_count"), 0)
        self.assertIs(metadata.get("test_passed"), True)
        self.assertEqual(metadata.get("framework"), "pytest")

    def test_errors_only_pytest_emits_test_passed_false(self):
        # Collection-only errors must NOT report as a green zero-test run.
        status = self._status("pytest", "===== 2 errors in 0.5s =====")
        metadata = status.get("metadata") or {}
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_PARSED)
        self.assertIs(metadata.get("test_passed"), False)
        self.assertEqual(metadata.get("test_count"), 2)
        self.assertEqual(metadata.get("test_errors"), 2)


if __name__ == "__main__":
    unittest.main()
