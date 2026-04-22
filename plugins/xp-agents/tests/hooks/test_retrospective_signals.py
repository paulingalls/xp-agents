#!/usr/bin/env python3
"""Tests for retrospective honesty signals, security counting, and code metrics.

Split from test_retrospective.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event

# -- Shared helpers for honesty-signal tests ----------------------------------


def _make_write_status(path: str) -> dict:
    return make_event("status", content=f"Wrote to {path}", working_on=[path])


def _make_test_status() -> dict:
    return make_event("status", content="Tests: 5 passed, 0 failed", working_on=[])


class TestHonestySignals(unittest.TestCase):
    """Tests for _build_honesty_signals unique file counting."""

    def test_counts_unique_files_not_raw_writes(self):
        """4 writes to same file between tests should count as 1."""
        import honesty_signals

        events = [
            _make_write_status("src/app.py"),
            _make_write_status("src/app.py"),
            _make_write_status("src/app.py"),
            _make_write_status("src/app.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_counts_different_files(self):
        """3 different files between tests should count as 3."""
        import honesty_signals

        events = [
            _make_write_status("src/app.py"),
            _make_write_status("src/db.py"),
            _make_write_status("src/api.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_resets_on_test_run(self):
        """Unique file set resets after each test run."""
        import honesty_signals

        events = [
            _make_write_status("src/app.py"),
            _make_write_status("src/db.py"),
            _make_test_status(),
            _make_write_status("src/api.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_excludes_test_files(self):
        """Test file writes should not count."""
        import honesty_signals

        events = [
            _make_write_status("tests/test_app.py"),
            _make_write_status("src/app.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_excludes_non_code_files(self):
        """Non-code files (md, json, etc) should not count."""
        import honesty_signals

        events = [
            _make_write_status("README.md"),
            _make_write_status("config.json"),
            _make_write_status("src/app.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)


class TestSecurityCheckCounting(unittest.TestCase):
    """Tests for commits_without_security_check counting in _build_honesty_signals."""

    def test_commit_event_without_security_check_counted(self):
        """Commit event without preceding security check is counted."""
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_security_check"], 1)
        self.assertEqual(signals["total_commits"], 1)

    def test_commit_event_with_triage_not_counted(self):
        """Commit preceded by /xp-security-triage event is not counted."""
        import honesty_signals

        events = [
            make_event(
                "status",
                content="Security triage started \u2014 reviewing staged changes",
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_security_check"], 0)

    def test_commit_event_with_security_review_not_counted(self):
        """Commit preceded by /security-review event is not counted."""
        import honesty_signals

        events = [
            make_event(
                "status",
                content="Security review complete \u2014 full review performed",
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "abc123"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_security_check"], 0)

    def test_non_code_commit_event_not_counted(self):
        """Non-code commit (docs-only) without security check is NOT counted."""
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Update docs",
                metadata={"code_commit": False},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_security_check"], 0)

    def test_legacy_status_commit_backward_compat(self):
        """Legacy status commit events still detected (backward compat)."""
        import honesty_signals

        events = [
            make_event("status", content="Committed: Old commit"),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["commits_without_security_check"], 1)
        self.assertEqual(signals["total_commits"], 1)


class TestCodeCommitsAndPlanningEvents(unittest.TestCase):
    """Tests for code_commits and planning_events in honesty_signals."""

    def test_counts_code_commits(self):
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Fix bug",
                metadata={"code_commit": True, "commit_hash": "abc"},
            ),
            make_event(
                "commit",
                content="Update docs",
                metadata={"code_commit": False, "commit_hash": "def"},
            ),
            make_event(
                "commit",
                content="Add feature",
                metadata={"code_commit": True, "commit_hash": "ghi"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["code_commits"], 2)

    def test_counts_planning_events(self):
        import honesty_signals

        events = [
            make_event(
                "status",
                content="plan_awaiting_review: Plan completed",
            ),
            make_event("status", content="Working on tests"),
            make_event(
                "status",
                content="plan_awaiting_review: Plan completed",
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 2)

    def test_no_planning_events(self):
        import honesty_signals

        events = [make_event("status", content="Working on tests")]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 0)


class TestReviewRequiredCommits(unittest.TestCase):
    """Tests for review_required_commits signal splitting."""

    def test_counts_review_required_commits(self):
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Big change",
                metadata={"code_commit": True, "code_file_count": 3},
            ),
            make_event(
                "commit",
                content="Small fix",
                metadata={"code_commit": True, "code_file_count": 1},
            ),
            make_event(
                "commit",
                content="Config only",
                metadata={"code_commit": False, "code_file_count": 0},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 1)
        self.assertEqual(signals["code_commits"], 2)

    def test_legacy_commits_default_review_required(self):
        import honesty_signals

        events = [
            make_event(
                "commit",
                content="Old commit",
                metadata={"code_commit": True, "commit_hash": "abc"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 1)


class TestCommitAsSignalEvent(_HookTestCase):
    """Commit events should appear in the retro digest as signal events."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_commit_in_signal_events(self):
        """Commit events flow through as signal events in the digest."""
        import retrospective

        commit = make_event(
            "commit",
            content="Fix auth bug\n\nDetailed explanation of the fix.",
            metadata={"commit_hash": "abc123", "code_commit": True},
            files=["src/auth.py"],
        )
        self._write_events([make_event()] * 5 + [commit])
        context = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(context)
        data = json.loads((self.smm_dir / ".retro-input.json").read_text())
        signal_types = [e["type"] for e in data["digest"]["signal_events"]]
        self.assertIn("commit", signal_types)


class TestRefactorModeExclusion(unittest.TestCase):
    """Tests for refactor-mode span exclusion in build_honesty_signals."""

    def _make_refactor_mode_assumption(
        self, content: str = "refactor mode: splitting modules"
    ) -> dict:
        return make_event("assumption", content=content)

    def _make_commit(self) -> dict:
        return make_event(
            "commit",
            content="Fix something",
            metadata={"code_commit": True, "commit_hash": "abc123"},
        )

    def test_refactor_mode_excludes_files(self):
        """File writes within a refactor-mode span should not count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            _make_write_status("src/app.py"),
            _make_write_status("src/db.py"),
            _make_write_status("src/api.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 0)

    def test_undeclared_batch_still_counts(self):
        """File writes without a refactor-mode assumption still count."""
        import honesty_signals

        events = [
            _make_write_status("src/app.py"),
            _make_write_status("src/db.py"),
            _make_write_status("src/api.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_refactor_mode_resets_on_commit(self):
        """Refactor-mode span ends at commit — subsequent writes count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            _make_write_status("src/app.py"),
            self._make_commit(),
            _make_write_status("src/db.py"),
            _make_write_status("src/api.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_refactor_mode_excluded_count(self):
        """refactor_mode_excluded_files key should reflect excluded count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            _make_write_status("src/app.py"),
            _make_write_status("src/db.py"),
            _make_test_status(),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["refactor_mode_excluded_files"], 2)

    def test_refactor_mode_case_insensitive(self):
        """Both 'Refactor Mode:' and 'refactor-mode' should match."""
        import honesty_signals

        for content in ["Refactor Mode: file split", "refactor-mode: renaming"]:
            events = [
                self._make_refactor_mode_assumption(content),
                _make_write_status("src/app.py"),
                _make_test_status(),
            ]
            signals = honesty_signals.build_honesty_signals(events)
            self.assertEqual(
                signals["max_unique_files_without_test"],
                0,
                f"Failed for content: {content}",
            )


if __name__ == "__main__":
    unittest.main()
