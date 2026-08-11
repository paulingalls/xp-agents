#!/usr/bin/env python3
"""Tests for bash_post_tool review-cycle marker lifecycle: reset after
commit, worktree-scoped markers, and reset across multi-commit sequences.

Split from test_bash_commit.py to stay under the file-size cap; see that
file's docstring for the sibling map.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import review_records

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
)


class TestBashPostToolReviewCycle(_HookTestCase):
    """Tests for review cycle marker reset after commit."""

    def test_commit_resets_review_cycle(self):
        """After commit, review cycle marker has new hash and cleared flags."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        watermark = review_records.read_review_watermark(self.smm_dir, "main")
        self.assertEqual(watermark, "newcommit123")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_commit_no_hash_skips_reset(self):
        """If git rev-parse fails, no marker written (no crash)."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
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
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_non_commit_no_reset(self):
        """Non-commit bash commands don't touch review cycle marker."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        bash_post_tool.run(
            _make_bash_input(command="echo hello", stdout="hello"),
            smm_dir=self.smm_dir,
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_failed_commit_preserves_review_cycle(self):
        """Pre-commit hook failure must not reset review flags."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'test'",
                    stdout="ruff-check >\n\nFAILED\npre-commit hook failed",
                ),
                smm_dir=self.smm_dir,
            )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        self.assertTrue(cycle["quality_review_done"])

    def test_empty_stdout_preserves_markers(self):
        """Content-agnostic guard: any non-success stdout short-circuits effects."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch("commits.get_head_commit_hash", return_value="prevhash"):
            bash_post_tool.run(
                _make_bash_input(command="git commit -m 'test'", stdout=""),
                smm_dir=self.smm_dir,
            )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])


class TestBashPostToolWorktreeAgentId(_HookTestCase):
    """Worktree cwd uses resolve_agent_id for commit handling."""

    def test_commit_resets_worktree_scoped_markers(self):
        """After commit, worktree-scoped markers are reset."""
        agent_id = "worktree-story-001"
        review_records.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        review_records.set_review_flag(self.smm_dir, agent_id, "quality_review_done")
        inp = _make_bash_input(
            command="git commit -m 'test'",
            stdout="[main abc123] test\n 1 file changed",
            agent_id="",
            cwd="/proj/.claude/worktrees/worktree-story-001",
        )
        with (
            patch("commits.get_committed_files", return_value=["a.py"]),
            patch(
                "commits.get_head_commit_hash",
                return_value="newcommit123",
            ),
        ):
            bash_post_tool.run(inp, smm_dir=self.smm_dir)
        cycle = review_records.read_review_flags(self.smm_dir, agent_id)
        watermark = review_records.read_review_watermark(self.smm_dir, agent_id)
        self.assertEqual(watermark, "newcommit123")
        self.assertFalse(cycle["simplify_done"])


class TestBashPostToolMultiCommitSequence(_HookTestCase):
    """Multi-commit sequences in a single session must each record a commit
    event AND each reset review-cycle markers.

    Captures real-world bugs ec4c804139e4 (post-commit hook stops recording
    commit events after the first in a session — Resolves-Event trailers
    never auto-close targets) and 731915a2d4d2 (review-cycle markers persist
    across commits — second commit can pass the gate without re-running the
    cycle). Existing single-commit tests in TestBashPostToolReviewCycle pass,
    so the bugs only surface when two commits run back-to-back through
    bash_post_tool.run.
    """

    def _run_commit(self, *, head_sha: str, body: str, files: list[str]):
        with patch_commits(files=files, body=body, head_sha=head_sha):
            return bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'work'",
                    stdout=f"[main {head_sha[:7]}] work\n 1 file changed",
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

    def test_two_consecutive_commits_each_record_commit_event(self):
        """Bug ec4c804139e4: every successful code commit must produce a
        commit event in events.jsonl, not just the first."""
        self._run_commit(
            head_sha="aaaaaaa1111111", body="first commit", files=["scripts/a.py"]
        )
        self._run_commit(
            head_sha="bbbbbbb2222222", body="second commit", files=["scripts/b.py"]
        )

        commits = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        hashes = [(e.get("metadata") or {}).get("commit_hash") for e in commits]
        self.assertEqual(
            len(commits),
            2,
            f"expected 2 commit events, got {len(commits)}: hashes={hashes}",
        )
        self.assertEqual(hashes, ["aaaaaaa1111111", "bbbbbbb2222222"])

    def test_resolves_event_trailer_auto_closes_open_concern(self):
        """Bug ec4c804139e4 (real-world fixture): commit 6cdd24f's body
        carried `Resolves-Event: 78ab5a70ca1b, 87e022ad0693` but neither
        concern auto-closed because the commit event itself was silently
        dropped, leaving metadata.resolves unwritten."""
        # Seed two open concerns matching the trailer IDs.
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="78ab5a70ca1b",
                    content="leading-slash drop",
                    severity="medium",
                ),
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="87e022ad0693",
                    content="python-bias extension list",
                    severity="medium",
                ),
            ]
        )

        # Two-commit sequence: a benign first commit, then the real fixture.
        self._run_commit(
            head_sha="ccccccc3333333", body="warm up", files=["scripts/x.py"]
        )
        body_with_trailer = (
            "[free] auto-extract: capture leading-slash + expand language set\n"
            "\n"
            "Resolves-Event: 78ab5a70ca1b, 87e022ad0693\n"
        )
        self._run_commit(
            head_sha="6cdd24fcb5a0",
            body=body_with_trailer,
            files=["plugins/xp-agents/smm/event_builder.py"],
        )

        # The second commit event should carry both IDs in metadata.resolves.
        commits = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        fixture_commits = [
            e
            for e in commits
            if (e.get("metadata") or {}).get("commit_hash") == "6cdd24fcb5a0"
        ]
        self.assertEqual(
            len(fixture_commits),
            1,
            f"fixture commit event missing; recorded={len(commits)}",
        )
        resolves = (fixture_commits[0].get("metadata") or {}).get("resolves") or []
        self.assertIn("78ab5a70ca1b", resolves)
        self.assertIn("87e022ad0693", resolves)

    def test_git_dash_C_commit_form_records_commit_event(self):
        """Bug ec4c804139e4 root cause: `git -C <path> commit ...` form
        is not recognized by is_git_commit's `\\bgit\\s+commit\\b` regex,
        so the post-commit hook never enters _handle_commit. The agent
        adopted `git -C` to avoid cd-poisoning Stop hooks (per feedback
        memory cd_persists_in_bash); that change silently broke the
        commit detector. 14 commits in sprint-052's free session went
        unrecorded for this reason."""
        real_command = (
            "git -C /Users/paulingalls/src/projects/xp-agents add scripts/x.py "
            "&& git -C /Users/paulingalls/src/projects/xp-agents commit -m "
            "\"$(cat <<'EOF'\n"
            "[free] tighten regex\n\n"
            "Resolves-Event: deadbeef0001\n"
            'EOF\n)"'
        )
        real_stdout = (
            "[paulingalls/some-branch abc1234] [free] tighten regex\n"
            " 1 file changed, 5 insertions(+), 2 deletions(-)\n"
        )
        with patch_commits(
            files=["scripts/x.py"],
            body="[free] tighten regex\n\nResolves-Event: deadbeef0001\n",
            head_sha="abc1234567890",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=real_command,
                    stdout=real_stdout,
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )
        commits = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(
            len(commits),
            1,
            "git -C <path> commit form must be recognized by is_git_commit "
            "and produce a commit event",
        )

    def test_real_world_b679c79_command_records_commit_event(self):
        """Replay commit b679c79 verbatim (real bash command + real git
        stdout). One of the 14 silent failures from sprint-052's free
        session. If the bug is in command/stdout shape, this surfaces it."""
        real_command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "[free] author-time concern --files nudge\n"
            "\n"
            "Mirror xp-close-reviewer.md:127's --files discipline across the other\n"
            "concern-filing surfaces:\n"
            "\n"
            "- xp-code-reviewer.md: explicit MUST sentence after the recording\n"
            "  template (concerns naming source paths must populate --files).\n"
            "\n"
            "Backstops A2's auto-extract: explicit always beats fallback.\n"
            "\n"
            "Resolves-Event: c008a0479ecd\n"
            "EOF\n"
            ')"'
        )
        real_stdout = (
            "[paulingalls/free-2026-05-03-concern-files-earlier-catch b679c79c1c2] "
            "[free] author-time concern --files nudge\n"
            " 3 files changed, 27 insertions(+), 8 deletions(-)\n"
        )
        # Seed an open concern matching the trailer ID.
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_CONCERN,
                    id="c008a0479ecd",
                    content="auto-extract concern",
                    severity="medium",
                ),
            ]
        )
        with patch_commits(
            files=[
                "plugins/xp-agents/agents/xp-code-reviewer.md",
                "plugins/xp-agents/agents/xp-system-analyzer.md",
                "plugins/xp-agents/skills/xp-accept/SKILL.md",
            ],
            body=(
                "[free] author-time concern --files nudge\n\n"
                "Resolves-Event: c008a0479ecd\n"
            ),
            head_sha="b679c79c1c2645fd0ea13bc9ada0711609d7595e",
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=real_command,
                    stdout=real_stdout,
                    cwd=str(self.smm_dir),
                ),
                smm_dir=self.smm_dir,
            )

        commits = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(
            len(commits),
            1,
            f"real-world b679c79 commit must record an event, got {len(commits)}",
        )
        resolves = (commits[0].get("metadata") or {}).get("resolves") or []
        self.assertIn("c008a0479ecd", resolves)

    def test_second_commit_also_resets_review_markers(self):
        """Bug 731915a2d4d2: review-cycle markers must reset after EVERY
        successful code commit, not just the first."""
        # Simulate /simplify + /xp-quality-review before commit 1.
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self._run_commit(
            head_sha="hash1111111111", body="first", files=["scripts/a.py"]
        )
        cycle1 = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle1["simplify_done"], "commit 1 must clear simplify_done")
        self.assertFalse(
            cycle1["quality_review_done"], "commit 1 must clear quality_review_done"
        )
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "hash1111111111"
        )

        # Simulate /simplify + /xp-quality-review again before commit 2.
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self._run_commit(
            head_sha="hash2222222222", body="second", files=["scripts/b.py"]
        )
        cycle2 = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(cycle2["simplify_done"], "commit 2 must clear simplify_done")
        self.assertFalse(
            cycle2["quality_review_done"], "commit 2 must clear quality_review_done"
        )
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "hash2222222222"
        )


if __name__ == "__main__":
    unittest.main()
