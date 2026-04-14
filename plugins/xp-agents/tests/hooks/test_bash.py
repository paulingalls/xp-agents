#!/usr/bin/env python3
"""Tests for bash_post_tool.py and bash_failure.py hooks.

Split from the original test_post_tool.py.
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
import bash_failure
import bash_post_tool
import commits
import markers
from conftest import _HookTestCase, _make_bash_input, _s, _sprint_json, make_event


class TestBashPostTool(_HookTestCase):
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
                agent_type="xp-housekeeping",
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


# ===========================================================================
# Review cycle reset on commit
# ===========================================================================


class TestBashPostToolReviewCycle(_HookTestCase):
    """Tests for review cycle marker reset after commit."""

    def test_commit_resets_review_cycle(self):
        """After commit, review cycle marker has new hash and cleared flags."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_head_commit_hash", return_value="newcommit123"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="[main abc123] test\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(cycle["last_review_commit"], "newcommit123")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])
        self.assertFalse(cycle["security_review_done"])

    def test_commit_no_hash_skips_reset(self):
        """If git rev-parse fails, no marker written (no crash)."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_head_commit_hash", return_value=None),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="[main abc123] test\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        # Flag should still be set — no reset happened
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_non_commit_no_reset(self):
        """Non-commit bash commands don't touch review cycle marker."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        bash_post_tool.run(
            _make_bash_input(command="echo hello", stdout="hello"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])


# ===========================================================================
# Bash Failure (PostToolUseFailure)
# ===========================================================================


def _make_bash_failure_input(
    command: str = "echo hi", error: str = "exit code 1", **overrides
) -> dict:
    """Build a canonical PostToolUseFailure Bash input dict."""
    data = {
        "session_id": "t",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": error,
        "is_interrupt": False,
        "agent_id": "main",
    }
    data.update(overrides)
    return data


class TestBashFailure(_HookTestCase):
    """Tests for bash_failure.py PostToolUseFailure handler."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_xp_agent_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_type="xp-nav"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_interrupt_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="interrupted", is_interrupt=True
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_no_smm_dir_degrades(self):
        inp = _make_bash_failure_input(command="pytest", error="exit 1")
        self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        # No crash

    def test_non_test_command_ignored(self):
        inp = _make_bash_failure_input(command="ls -la", error="exit 2")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_pytest_failure_records_status_and_concern(self):
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertIn("non-zero status code 2", statuses[0]["content"])


class TestBashFailureSecurity(_HookTestCase):
    """Security tests for bash_failure.py."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_path_traversal_agent_id_rejected(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_id="../../evil"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


class TestResolveTestConcerns(_HookTestCase):
    """Tests for bash_post_tool._resolve_test_concerns."""

    def test_resolves_test_concern(self):
        """Test concerns are resolved when tests pass."""
        # Seed a test-failure concern
        concern = make_event(
            "concern", content="Test failures detected: 3 failed", severity="high"
        )
        _common.append_safe(self.smm_dir, concern)

        bash_post_tool._resolve_test_concerns(self.smm_dir, "main")

        events = _common.read_events_raw(self.smm_dir)
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)

    def test_no_concerns_no_resolution(self):
        """No test concerns → no resolution events."""
        bash_post_tool._resolve_test_concerns(self.smm_dir, "main")
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


class TestBashPostToolWorktreeAgentId(_HookTestCase):
    """Worktree cwd uses resolve_agent_id for commit handling."""

    def test_commit_resets_worktree_scoped_markers(self):
        """After commit, worktree-scoped markers are reset."""
        agent_id = "teammate-story-001"
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        markers.set_review_flag(self.smm_dir, agent_id, "security_review_done")
        inp = _make_bash_input(
            command="git commit -m 'test'",
            stdout="[main abc123] test\n 1 file changed",
            agent_id="",
            cwd="/proj/.claude/worktrees/teammate-story-001",
        )
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch(
                "commits.get_head_commit_hash",
                return_value="newcommit123",
            ),
        ):
            bash_post_tool.run(inp, smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, agent_id)
        self.assertEqual(cycle["last_review_commit"], "newcommit123")
        self.assertFalse(cycle["simplify_done"])


class TestBashPostToolGreenNudge(_HookTestCase):
    """Tests for commit-after-green nudge in bash_post_tool."""

    def test_green_with_uncommitted_code_returns_nudge(self):
        """All tests pass + uncommitted code files → nudge string returned."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNotNone(result)
        self.assertIn("commit", result.lower())

    def test_green_no_uncommitted_code_no_nudge(self):
        """All tests pass but no uncommitted code files → no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=[]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_green_after_failure_confirms_resolution(self):
        """Tests pass after prior failure → context confirms resolution."""
        # Seed a test failure concern
        concern = make_event(
            "concern", content="Test failures detected: 3 failed", severity="high"
        )
        _common.append_safe(self.smm_dir, concern)

        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 5 passed in 0.3s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNotNone(result)
        self.assertIn("prior test failures resolved", result.lower())
        self.assertIn("commit", result.lower())

    def test_red_no_nudge(self):
        """Failing tests → no nudge (even with uncommitted code)."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="===== 3 passed, 2 failed in 1.2s =====",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_xp_agent_no_nudge(self):
        """xp- agents never get the nudge (recursion guard)."""
        result = bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
                agent_type="xp-simplify",
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_zero_passed_zero_failed_no_nudge(self):
        """Ambiguous output (0 passed, 0 failed) → no nudge."""
        with patch("commits.get_uncommitted_code_files", return_value=["src/app.py"]):
            result = bash_post_tool.run(
                _make_bash_input(
                    command="python3 -m pytest tests/",
                    stdout="no tests ran",
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)


class TestBashPostToolPushWarning(_HookTestCase):
    """Tests for git push session-end checklist nudge."""

    def test_push_with_unresolved_concerns_warns(self):
        """git push with unresolved concerns returns session-end checklist."""
        self._write_events(
            [make_event("concern", content="Open issue", severity="medium")]
        )
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("concern", result.lower())

    def test_push_always_nudges_summary(self):
        """git push always nudges session summary for user."""
        self._write_events([make_event("status", content="All done")])
        result = bash_post_tool.run(
            _make_bash_input(command="git push origin main", stdout=""),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("summarize", result.lower())

    def test_push_xp_agent_skips(self):
        """xp- agents skip push warning."""
        result = bash_post_tool.run(
            _make_bash_input(
                command="git push origin main",
                stdout="",
                agent_type="xp-nav",
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# _resolve_story_id — three-tier story attribution
# ===========================================================================


class TestResolveStoryId(_HookTestCase):
    """Tests for _resolve_story_id: three-tier commit-to-story attribution."""

    def test_tier1_teammate_reads_assignment_file(self):
        """Teammate with .story-assignment file returns its story_id."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.write_text("story-001")
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/app.py"],
        )
        self.assertEqual(result, "story-001")

    def test_tier1_no_assignment_falls_through(self):
        """Teammate without assignment file falls through to tier 2/3."""
        result = bash_post_tool._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/app.py"],
        )
        self.assertIsNone(result)

    def test_tier2_solo_single_in_progress(self):
        """Solo sprint with one in-progress story attributes to it."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    )
                ],
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertEqual(result, "story-001")

    def test_tier2_solo_multiple_tiebreak_by_overlap(self):
        """Multiple in-progress stories tiebreak by file domain overlap."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["src/ui.py", "src/util.py"]
        )
        self.assertEqual(result, "story-002")

    def test_tier2_solo_multiple_no_overlap_returns_none(self):
        """Multiple in-progress stories with no overlap returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "M",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "M",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["unrelated.py"]
        )
        self.assertIsNone(result)

    def test_tier3_no_sprint_returns_none(self):
        """No sprint.json returns None."""
        result = bash_post_tool._resolve_story_id(self.smm_dir, "/proj", ["setup.py"])
        self.assertIsNone(result)

    def test_tier3_no_in_progress_stories(self):
        """Sprint with no in-progress stories returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "M",
                        "done",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                ]
            )
        )
        result = bash_post_tool._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertIsNone(result)

    def test_commit_metadata_includes_story_id(self):
        """Commit event metadata includes story_id when resolved."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "teammate-step-1")
        assignment.write_text("story-003")

        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value="Add feature"),
            patch("commits.get_head_commit_hash", return_value="def456"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main def456] Add feature\n 1 file changed",
                    cwd="/proj/.claude/worktrees/teammate-step-1",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commit_ev), 1)
        self.assertEqual(commit_ev[0]["metadata"]["story_id"], "story-003")

    def test_commit_metadata_no_story_id_when_not_resolved(self):
        """Commit event metadata omits story_id when not resolved."""
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch("commits.get_commit_message_body", return_value="Fix bug"),
            patch("commits.get_head_commit_hash", return_value="aaa111"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main aaa111] Fix bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        commit_ev = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commit_ev), 1)
        self.assertNotIn("story_id", commit_ev[0]["metadata"])


if __name__ == "__main__":
    unittest.main()
