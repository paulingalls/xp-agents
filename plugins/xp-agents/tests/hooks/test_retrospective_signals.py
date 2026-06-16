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

from conftest import (
    _HookTestCase,
    file_write_status,
    make_event,
    tests_run_status,
)
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)


class TestHonestySignals(unittest.TestCase):
    """Tests for _build_honesty_signals unique file counting."""

    def test_counts_unique_files_not_raw_writes(self):
        """4 writes to same file between tests should count as 1."""
        import honesty_signals

        events = [
            file_write_status("src/app.py"),
            file_write_status("src/app.py"),
            file_write_status("src/app.py"),
            file_write_status("src/app.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_counts_different_files(self):
        """3 different files between tests should count as 3."""
        import honesty_signals

        events = [
            file_write_status("src/app.py"),
            file_write_status("src/db.py"),
            file_write_status("src/api.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_resets_on_test_run(self):
        """Unique file set resets after each test run."""
        import honesty_signals

        events = [
            file_write_status("src/app.py"),
            file_write_status("src/db.py"),
            tests_run_status(count=5),
            file_write_status("src/api.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_excludes_test_files(self):
        """Test file writes should not count."""
        import honesty_signals

        events = [
            file_write_status("tests/test_app.py"),
            file_write_status("src/app.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_excludes_non_code_files(self):
        """Non-code files (md, json, etc) should not count."""
        import honesty_signals

        events = [
            file_write_status("README.md"),
            file_write_status("config.json"),
            file_write_status("src/app.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_uses_metadata_files_when_action_present(self):
        """sprint-042 M2: when metadata.action=file_write, the path is sourced
        from metadata.files[0] — not parsed from content. Content is opaque."""
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="x",  # deliberately non-matching for the regex path
                working_on=["src/app.py"],
                metadata={"action": STATUS_ACTION_FILE_WRITE, "files": ["src/app.py"]},
            ),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["code_file_writes"], 1)
        self.assertEqual(signals["max_unique_files_without_test"], 1)

    def test_test_run_action_resets_window(self):
        """sprint-042 M2: action=test_run_complete resets unique_files_since_test
        identically to the legacy regex branch."""
        import honesty_signals

        events = [
            file_write_status("src/a.py"),
            file_write_status("src/b.py"),
            make_event(
                EVENT_TYPE_STATUS,
                content="opaque",
                metadata={
                    "action": STATUS_ACTION_TEST_RUN_COMPLETE,
                    "test_passed": True,
                },
            ),
            file_write_status("src/c.py"),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        # Window resets after the action event, so the post-test write
        # is counted in a fresh window.
        self.assertEqual(signals["max_unique_files_without_test"], 2)


class TestCodeCommitsAndPlanningEvents(unittest.TestCase):
    """Tests for code_commits and planning_events in honesty_signals."""

    def test_counts_code_commits(self):
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="Fix bug",
                metadata={"code_commit": True, "commit_hash": "abc"},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="Update docs",
                metadata={"code_commit": False, "commit_hash": "def"},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
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
                EVENT_TYPE_STATUS,
                content="plan_awaiting_review: Plan completed",
            ),
            make_event(EVENT_TYPE_STATUS, content="Working on tests"),
            make_event(
                EVENT_TYPE_STATUS,
                content="plan_awaiting_review: Plan completed",
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 2)

    def test_no_planning_events(self):
        import honesty_signals

        events = [make_event(EVENT_TYPE_STATUS, content="Working on tests")]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["planning_events"], 0)


class TestReviewRequiredCommits(unittest.TestCase):
    """Tests for review_required_commits signal splitting."""

    def test_counts_review_required_commits(self):
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="Big change",
                metadata={"code_commit": True, "code_file_count": 3},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="Small fix",
                metadata={"code_commit": True, "code_file_count": 1},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
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
                EVENT_TYPE_COMMIT,
                content="Old commit",
                metadata={"code_commit": True, "commit_hash": "abc"},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 1)

    def test_merge_commits_excluded_from_review_required(self):
        """Merge HEADs aggregate already-reviewed work — they don't require
        their own review, so they must not inflate the denominator."""
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="Merge branch feature/x",
                metadata={
                    "code_commit": True,
                    "code_file_count": 3,
                    "is_merge": True,
                },
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 0)
        # Still counts toward code_commits — only the review denominator changes.
        self.assertEqual(signals["code_commits"], 1)

    def test_escape_hatch_commits_excluded_from_review_required(self):
        """[release]/[chore]/[sprint-direct] commits bypass the review-cycle
        gate by design, so they never require a review and must not land in
        the quality_reviews_missing denominator (retro false positive)."""
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="[release] xp-agents 3.6.0 — guardrails",
                metadata={"code_commit": True, "code_file_count": 3},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="[chore] bump pinned versions",
                metadata={"code_commit": True, "code_file_count": 3},
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="[sprint-direct] hotfix the gate",
                metadata={"code_commit": True, "code_file_count": 3},
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 0)
        self.assertEqual(signals["code_commits"], 3)

    def test_story_cadence_commits_excluded_from_review_required(self):
        """In story review-cadence the per-commit review is deferred to
        /xp-story-close (which reviews the cumulative diff and ticks
        quality_reviews once). Intermediate story-cadence commits therefore
        don't individually require a review — counting them inflates the
        quality_reviews_missing denominator and fires the Feedback flag
        falsely (far fewer reviews than commits is BY DESIGN in story mode).
        """
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="Story step 1",
                metadata={
                    "code_commit": True,
                    "code_file_count": 3,
                    "review_cadence": "story",
                },
            ),
            make_event(
                EVENT_TYPE_COMMIT,
                content="Story step 2",
                metadata={
                    "code_commit": True,
                    "code_file_count": 4,
                    "review_cadence": "story",
                },
            ),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["review_required_commits"], 0)
        # Still real code commits — only the review denominator changes.
        self.assertEqual(signals["code_commits"], 2)

    def test_commit_cadence_commits_still_review_required(self):
        """A commit explicitly tagged commit-cadence (or untagged, the
        default) still requires a per-commit review — the story exemption
        must not over-reach and silence the genuine commit-cadence signal.
        """
        import honesty_signals

        events = [
            make_event(
                EVENT_TYPE_COMMIT,
                content="Commit-cadence change",
                metadata={
                    "code_commit": True,
                    "code_file_count": 3,
                    "review_cadence": "commit",
                },
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
            EVENT_TYPE_COMMIT,
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
        return make_event(EVENT_TYPE_ASSUMPTION, content=content)

    def _make_commit(self) -> dict:
        return make_event(
            EVENT_TYPE_COMMIT,
            content="Fix something",
            metadata={"code_commit": True, "commit_hash": "abc123"},
        )

    def test_refactor_mode_excludes_files(self):
        """File writes within a refactor-mode span should not count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            file_write_status("src/app.py"),
            file_write_status("src/db.py"),
            file_write_status("src/api.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 0)

    def test_undeclared_batch_still_counts(self):
        """File writes without a refactor-mode assumption still count."""
        import honesty_signals

        events = [
            file_write_status("src/app.py"),
            file_write_status("src/db.py"),
            file_write_status("src/api.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 3)

    def test_refactor_mode_resets_on_commit(self):
        """Refactor-mode span ends at commit — subsequent writes count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            file_write_status("src/app.py"),
            self._make_commit(),
            file_write_status("src/db.py"),
            file_write_status("src/api.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["max_unique_files_without_test"], 2)

    def test_refactor_mode_excluded_count(self):
        """refactor_mode_excluded_files key should reflect excluded count."""
        import honesty_signals

        events = [
            self._make_refactor_mode_assumption(),
            file_write_status("src/app.py"),
            file_write_status("src/db.py"),
            tests_run_status(count=5),
        ]
        signals = honesty_signals.build_honesty_signals(events)
        self.assertEqual(signals["refactor_mode_excluded_files"], 2)

    def test_refactor_mode_case_insensitive(self):
        """Both 'Refactor Mode:' and 'refactor-mode' should match."""
        import honesty_signals

        for content in ["Refactor Mode: file split", "refactor-mode: renaming"]:
            events = [
                self._make_refactor_mode_assumption(content),
                file_write_status("src/app.py"),
                tests_run_status(count=5),
            ]
            signals = honesty_signals.build_honesty_signals(events)
            self.assertEqual(
                signals["max_unique_files_without_test"],
                0,
                f"Failed for content: {content}",
            )


if __name__ == "__main__":
    unittest.main()
