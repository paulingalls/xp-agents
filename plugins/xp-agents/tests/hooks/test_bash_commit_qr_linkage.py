#!/usr/bin/env python3
"""Tests for bash_post_tool QR linkage warnings + canonical action events.

Covers: TestQRLinkageWarning (per-commit quality-review linkage),
TestResolutionComputationCount (single-pass guarantee),
TestCheckQRLinkagePhrasings (varied QR completion wording),
TestM2CommitSuccessAction + TestM2LintResolvedAction (deterministic
event emission doctrine — sprint-041/042 M2). Split from
test_bash_commit.py.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import commit_handling
import markers
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _ProbeTestHelpers, make_event
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_QR_COMPLETE,
)

_WATERMARK_ID = "test-bash-commit-qr-linkage"


class TestQRLinkageWarning(_ProbeTestHelpers, _HookTestCase):
    """Per-commit quality-review linkage warning."""

    def _seed_commit_event(self, agent_id: str = "main") -> str:
        ev = make_event(EVENT_TYPE_COMMIT, agent_id=agent_id, content="Prior commit")
        _common.append_safe(self.smm_dir, ev)
        return ev["id"]

    def _seed_qr_status(self, agent_id: str = "xp-quality-review") -> str:
        ev = make_event(
            EVENT_TYPE_STATUS,
            agent_id=agent_id,
            content="Quality review complete. No issues: [].",
            metadata={"action": STATUS_ACTION_QR_COMPLETE},
        )
        _common.append_safe(self.smm_dir, ev)
        return ev["id"]

    def _run_commit(
        self,
        agent_id: str = "main",
        committed_files: list[str] | None = None,
    ) -> str | None:
        with patch_commits(
            files=committed_files or ["src/app.py"],
            body="Fix stuff",
            head_sha="def456",
        ):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix stuff'",
                    stdout="[main def456] Fix stuff\n 1 file changed",
                    cwd=str(self.smm_dir),
                    agent_id=agent_id,
                ),
                smm_dir=self.smm_dir,
            )

    def test_qr_event_between_commits_no_warning(self):
        self._seed_commit_event()
        self._seed_qr_status()
        result = self._run_commit()
        if result:
            self.assertNotIn("quality review", result.lower())

    def test_no_qr_event_since_previous_commit_warns(self):
        self._seed_commit_event()
        result = self._run_commit()
        assert result is not None
        self.assertIn("quality review", result.lower())

    def test_no_marker_no_qr_event_warns(self):
        result = self._run_commit()
        assert result is not None
        self.assertIn("quality review", result.lower())

    def test_back_to_back_commits_second_warns(self):
        self._seed_commit_event()
        self._seed_qr_status()
        self._seed_commit_event()
        result = self._run_commit()
        assert result is not None
        self.assertIn("quality review", result.lower())

    def test_qr_from_different_agent_still_suppresses(self):
        self._seed_commit_event()
        self._seed_qr_status(agent_id="xp-quality-review")
        result = self._run_commit()
        if result:
            self.assertNotIn("quality review", result.lower())

    def test_doc_only_commit_does_not_warn(self):
        # User-reported noise: doc-only commits (DEMO.md, README.md, etc.)
        # currently fire the "No quality review found" warning even though
        # /xp-quality-review only applies to code changes. Gate the nudge
        # on at least one staged code file.
        self._seed_commit_event()
        result = self._run_commit(committed_files=["DEMO.md"])
        if result:
            self.assertNotIn("quality review", result.lower())

    def test_config_only_commit_does_not_warn(self):
        # JSON/YAML config files are also non-code per code_files.is_code_file.
        self._seed_commit_event()
        result = self._run_commit(committed_files=["package.json", "config.yaml"])
        if result:
            self.assertNotIn("quality review", result.lower())

    def test_mixed_code_and_doc_still_warns(self):
        # Even one code file in a multi-file commit should preserve the nudge.
        self._seed_commit_event()
        result = self._run_commit(committed_files=["DEMO.md", "src/app.py"])
        assert result is not None
        self.assertIn("quality review", result.lower())


class TestResolutionComputationCount(_HookTestCase):
    """Verify _handle_commit computes resolutions exactly once."""

    def test_multi_file_commit_computes_resolutions_once(self):
        """Multiple committed files should not re-compute resolutions per file."""
        import resolution
        import worktree

        cwd = str(self.smm_dir)
        norm_a = worktree.normalize_path("scripts/auth.py", cwd)
        norm_b = worktree.normalize_path("scripts/routes.py", cwd)

        c1 = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm_a}:\nE302",
            severity="medium",
        )
        c2 = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm_b}:\nE303",
            severity="medium",
        )
        self._write_events([c1, c2])

        with (
            patch_commits(
                files=["scripts/auth.py", "scripts/routes.py"],
                body="Fix lint",
            ),
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
            patch("lint_check.run_linter", return_value=None),
            patch(
                "resolution.compute_resolutions",
                wraps=resolution.compute_resolutions,
            ) as mock_compute,
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix lint'",
                    stdout="[main abc123] Fix lint\n 2 files changed",
                    cwd=cwd,
                ),
                smm_dir=self.smm_dir,
            )
            self.assertEqual(mock_compute.call_count, 1)


class TestCheckQRLinkagePhrasings(unittest.TestCase):
    """_check_qr_linkage recognizes varied QR completion phrasings."""

    def test_qr_abbreviation_satisfies_nudge(self):
        events = [
            make_event(EVENT_TYPE_COMMIT, content="prior commit", agent_id="main"),
            make_event(
                EVENT_TYPE_STATUS,
                content="QR complete. Fixed: chrome.ts",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        ]
        result = commit_handling._check_qr_linkage(events, "main")
        self.assertIsNone(result)


class TestCadenceAwareQRLinkage(unittest.TestCase):
    """_check_qr_linkage respects the active review cadence (story-009)."""

    def _events_no_qr(self) -> list[dict]:
        return [make_event(EVENT_TYPE_COMMIT, content="prior commit", agent_id="main")]

    def test_story_cadence_no_qr_is_silent(self):
        result = commit_handling._check_qr_linkage(
            self._events_no_qr(), "main", cadence="story"
        )
        self.assertIsNone(result)

    def test_commit_cadence_no_qr_warns_verbatim(self):
        result = commit_handling._check_qr_linkage(
            self._events_no_qr(), "main", cadence="commit"
        )
        self.assertEqual(
            result,
            "No quality review found since previous commit. "
            "Run /xp-quality-review before committing.",
        )

    def test_qr_ran_since_previous_commit_silent_under_story_cadence(self):
        events = [
            make_event(EVENT_TYPE_COMMIT, content="prior commit", agent_id="main"),
            make_event(
                EVENT_TYPE_STATUS,
                content="Quality review complete.",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        ]
        result = commit_handling._check_qr_linkage(events, "main", cadence="story")
        self.assertIsNone(result)

    def test_qr_ran_since_previous_commit_silent_under_commit_cadence(self):
        events = [
            make_event(EVENT_TYPE_COMMIT, content="prior commit", agent_id="main"),
            make_event(
                EVENT_TYPE_STATUS,
                content="Quality review complete.",
                metadata={"action": STATUS_ACTION_QR_COMPLETE},
            ),
        ]
        result = commit_handling._check_qr_linkage(events, "main", cadence="commit")
        self.assertIsNone(result)


class TestStoryCadenceWiring(_ProbeTestHelpers, _HookTestCase):
    """End-to-end pin: _handle_commit must actually pass the marker's cadence
    through to _check_qr_linkage — a unit test on _check_qr_linkage alone
    would pass even if commit_handling.py never threaded the argument."""

    def _run_commit(self, agent_id: str = "main") -> str | None:
        with patch_commits(files=["src/app.py"], body="Fix stuff", head_sha="def456"):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix stuff'",
                    stdout="[main def456] Fix stuff\n 1 file changed",
                    cwd=str(self.smm_dir),
                    agent_id=agent_id,
                ),
                smm_dir=self.smm_dir,
            )

    def test_story_cadence_marker_silences_the_commit_nudge(self):
        ev = make_event(EVENT_TYPE_COMMIT, agent_id="main", content="Prior commit")
        _common.append_safe(self.smm_dir, ev)
        markers.write_review_cadence(self.smm_dir, "story")
        result = self._run_commit()
        # Unconditional: the sibling test below proves this exact setup DOES
        # warn without the marker, so silence here is the signal. A
        # `if result: assertNotIn(...)` guard would pass vacuously the day
        # the commit stops being recorded at all.
        self.assertIsNone(result)

    def test_missing_marker_falls_back_to_commit_cadence_nudge(self):
        ev = make_event(EVENT_TYPE_COMMIT, agent_id="main", content="Prior commit")
        _common.append_safe(self.smm_dir, ev)
        result = self._assert_not_none(self._run_commit())
        self.assertIn("quality review", result.lower())


class TestM2CommitSuccessAction(_HookTestCase):
    """sprint-042 M2: type=commit events carry metadata.action=commit_success
    alongside the existing commit_hash/code_commit/code_file_count fields."""

    def test_commit_event_carries_commit_success_action(self):
        with patch_commits(files=["scripts/foo.py"], body="Add foo"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add foo'",
                    stdout="[main abc1234] Add foo\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        commits = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commits), 1)
        metadata = commits[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "commit_success")
        # Existing metadata fields stay populated.
        self.assertIn("commit_hash", metadata)
        self.assertTrue(metadata.get("code_commit"))


class TestM2LintResolvedAction(_HookTestCase):
    """sprint-042 M2: lint resolver event carries metadata.action=lint_resolved."""

    def test_lint_resolved_event_carries_action(self):
        # Seed an unresolved lint concern that matches the file we'll commit.
        from concerns import LINT_CONCERN_PREFIX

        seeded = make_event(
            EVENT_TYPE_CONCERN,
            content=f"{LINT_CONCERN_PREFIX}scripts/foo.py: 1 error (X)",
            files=["scripts/foo.py"],
        )
        _common.append_safe(self.smm_dir, seeded)

        # Force the linter to report no errors so the concern resolves.
        # Patch normalize_path to identity so the seeded relative path matches
        # the committed file path exactly (no cwd-prefixing).
        with (
            patch_commits(files=["scripts/foo.py"], body="Fix lint"),
            patch("worktree.normalize_path", side_effect=lambda p, _cwd: p),
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", "ruff.toml"),
            ),
            patch("lint_check.run_linter", return_value=None),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix lint'",
                    stdout="[main abc1234] Fix lint\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        resolvers = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and "Lint concern resolved" in e.get("content", "")
        ]
        self.assertEqual(len(resolvers), 1)
        metadata = resolvers[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), "lint_resolved")


if __name__ == "__main__":
    unittest.main()
