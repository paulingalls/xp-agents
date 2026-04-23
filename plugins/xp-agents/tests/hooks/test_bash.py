#!/usr/bin/env python3
"""Tests for bash_post_tool.py: commit events, test framework detection, and
auto-link probe nudges.

Probe dedup, review cycle, green nudge, push warning, and QR linkage are in
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
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event


class TestBashPostTool(_ProbeTestHelpers, _HookTestCase):
    def test_git_commit_records_commit_event(self):
        with (
            patch("commits.get_committed_files", return_value=["a", "b", "c"]),
            patch("commits.get_commit_message_body", return_value="Add auth"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add auth'",
                    stdout="[main abc123] Add auth\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commits_ev = [e for e in events if e.get("type") == "commit"]
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
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value=body),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix the thing'",
                    stdout="[main abc123] Fix the thing\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = next(e for e in events if e.get("type") == "commit")
        self.assertEqual(
            commit_ev["metadata"]["resolves"],
            ["4eb35ddcd24e", "a55290ae79b9"],
        )

    def test_git_commit_no_resolves_trailer_omits_key(self):
        """Absent trailer must not add a resolves key to metadata."""
        body = "Fix the thing\n\nNo trailer here."
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value=body),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix'",
                    stdout="[main abc123] Fix\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = next(e for e in events if e.get("type") == "commit")
        self.assertNotIn("resolves", commit_ev["metadata"])

    def test_git_commit_strips_co_author_trailer(self):
        body = (
            "Fix the bug\n\nDetailed explanation.\n\nCo-Authored-By: Someone <x@y.com>"
        )
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value=body),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix the bug'",
                    stdout="[main abc123] Fix the bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commits_ev = [e for e in events if e.get("type") == "commit"]
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
        concerns = [e for e in events if e.get("type") == "concern"]
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
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("12 files" in c["content"] for c in concerns))

    def test_commit_code_files_has_code_commit_metadata(self):
        """Commit event has metadata.code_commit=True when code files present."""
        with (
            patch(
                "commits.get_committed_files",
                return_value=["src/app.py", "tests/test_app.py"],
            ),
            patch("commits.get_commit_message_body", return_value="Add feature"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main abc123] Add feature\n 2 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(committed), 1)
        self.assertTrue(committed[0].get("metadata", {}).get("code_commit"))

    def test_commit_no_code_files_has_code_commit_false(self):
        """Commit event has metadata.code_commit=False for docs-only commits."""
        with (
            patch(
                "commits.get_committed_files",
                return_value=["README.md", "docs/guide.md"],
            ),
            patch("commits.get_commit_message_body", return_value="Update docs"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Update docs'",
                    stdout="[main abc123] Update docs\n 2 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = [e for e in events if e.get("type") == "commit"]
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
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value="feat"),
            patch("commits.get_head_commit_hash", return_value="abc123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'feat'",
                    stdout="[main abc123] feat\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        committed = [e for e in events if e.get("type") == "commit"]
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
        statuses = [e for e in events if e.get("type") == "status"]
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
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            _make_bash_input(command="npx jest", stdout="Tests:  5 passed, 5 total"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
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
        concerns = [e for e in events if e.get("type") == "concern"]
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
        statuses = [e for e in events if e.get("type") == "status"]
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
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            _make_bash_input(command="ls -la", stdout="total 0"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips(self):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'x'",
                stdout="[main a] x",
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
        with (
            patch("commits.get_committed_files", return_value=committed_files),
            patch("commits.get_commit_message_body", return_value=body),
            patch("commits.get_head_commit_hash", return_value=commit_hash),
        ):
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

    def test_commit_emits_concern_autolink_nudge_on_file_overlap(self):
        """Commit touches a file in open concern's files -> additionalContext nudge."""
        cid = self._seed_auth_concern()
        result = self._run_auth_fix(body="Fix auth\n\nNo trailer here.")
        self.assertIsNotNone(result)
        self.assertIn(cid, result)
        self.assertIn("Resolves-Event", result)

    def _seed_qr_status(self) -> None:
        """Seed a quality-review status event to suppress QR-linkage warning."""
        _common.append_safe(
            self.smm_dir,
            make_event("status", content="Quality review complete. No issues."),
        )

    def test_commit_no_nudge_when_concern_resolved_by_trailer(self):
        """Resolves-Event trailer covering the matching concern -> no nudge."""
        cid = self._seed_auth_concern()
        self._seed_qr_status()
        result = self._run_auth_fix(body=f"Fix auth\n\nResolves-Event: {cid}")
        self.assertIsNone(result)

    def test_commit_no_nudge_when_no_file_overlap(self):
        """Concern's files don't intersect commit files -> no nudge."""
        concern = make_event("concern", content="Other bug", files=["scripts/foo.py"])
        _common.append_safe(self.smm_dir, concern)
        self._seed_qr_status()
        result = self._run_commit(
            body="Update README\n\nNo trailer.",
            committed_files=["README.md"],
            commit_msg="Update README",
        )
        self.assertIsNone(result)

    def test_nudge_includes_actionable_amend_trailer_command(self):
        """Nudge must spell out the full `git commit --amend --trailer` command."""
        cid = self._seed_auth_concern()
        result = self._run_auth_fix()
        self.assertIsNotNone(result)
        self.assertIn(f'git commit --amend --trailer "Resolves-Event: {cid}"', result)

    def test_probe_event_emitted_when_nudge_fires(self):
        """Nudge fires -> status event with probe_candidates + commit_hash."""
        cid = self._seed_auth_concern()
        self._run_auth_fix()
        probes = self._probes()
        self.assertEqual(len(probes), 1)
        probe = probes[0]
        self.assertEqual(probe["content"], "resolves_probe_shown: 1 candidates")
        self.assertEqual(probe["metadata"]["probe_candidates"], [cid])
        self.assertEqual(probe["metadata"]["commit_hash"], "abc123")

    def test_no_probe_event_when_no_candidates(self):
        """No matching concerns -> no resolves_probe_shown status event."""
        self._run_commit(
            body="Update README\n\nNo trailer.",
            committed_files=["README.md"],
            commit_msg="Update README",
        )
        self.assertEqual(self._probes(), [])

    def test_probe_caps_candidates_at_five(self):
        """>5 matching concerns -> only 5 IDs in nudge AND probe metadata."""
        cids = [self._seed_auth_concern(f"Concern number {i}") for i in range(7)]
        result = self._run_auth_fix()
        self.assertIsNotNone(result)
        for included_id in cids[:5]:
            self.assertIn(included_id, result)
        for excluded_id in cids[5:]:
            self.assertNotIn(excluded_id, result)

        probe = self._probes()[0]
        self.assertEqual(probe["content"], "resolves_probe_shown: 5 candidates")
        self.assertEqual(probe["metadata"]["probe_candidates"], cids[:5])

    def test_probe_event_records_null_commit_hash_when_rev_parse_fails(self):
        """commit_hash=None when git rev-parse fails; probe still emits."""
        self._seed_auth_concern()
        self._run_auth_fix(commit_hash=None)
        probe = self._probes()[0]
        self.assertIsNone(probe["metadata"]["commit_hash"])


if __name__ == "__main__":
    unittest.main()
