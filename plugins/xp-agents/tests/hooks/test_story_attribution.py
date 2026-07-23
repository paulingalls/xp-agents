#!/usr/bin/env python3
"""Tests for _resolve_story_id — four-tier commit-to-story attribution.

Split from test_bash.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import commit_handling
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _s, _sprint_json
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT

_WATERMARK_ID = "test-story-attribution"


class TestResolveStoryId(_HookTestCase):
    """Tests for _resolve_story_id: four-tier commit-to-story attribution."""

    def test_tier1_teammate_reads_assignment_file(self):
        """Teammate with .story-assignment file returns its story_id."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-001")
        assignment.write_text("story-001")
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/worktree-story-001",
            ["src/app.py"],
        )
        self.assertEqual(result, "story-001")

    def test_tier1_no_assignment_falls_through(self):
        """Teammate without assignment file falls through to tier 2/3."""
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/teammate-step-1",
            ["src/app.py"],
        )
        self.assertIsNone(result)

    def test_tier1_in_place_teammate_keys_on_env_name(self):
        """In-place teammate (main-checkout cwd, no worktree marker) attributes
        via the XP_TEAMMATE_NAME-keyed assignment file — explicitly, NOT via the
        single-in-progress heuristic. Two stories are in-progress here, so the
        heuristic would mis-attribute; the env-derived Tier 1 must win."""
        import os
        from unittest import mock

        import worktree

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "Auth", "in-progress", file_domain=["a.py"]),
                    _s("story-002", "Api", "in-progress", file_domain=["b.py"]),
                ],
            )
        )
        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-002")
        assignment.write_text("story-002")
        # A live in-place teammate has the lifetime-scoped marker written by
        # spawn_teammate — required before the env-derived name is trusted.
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-002")
        with mock.patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-002"}):
            # cwd is the MAIN checkout (no worktree path marker).
            result = commit_handling._resolve_story_id(
                self.smm_dir, "/proj", ["a.py", "b.py"]
            )
        self.assertEqual(result, "story-002")

    def test_in_place_env_without_marker_falls_through(self):
        """Leaked XP_TEAMMATE_NAME in the lead + a STALE assignment file but NO
        live in-place marker → the env name is NOT trusted. The lead's own
        commit attributes to the actually-in-progress story via the heuristic,
        not the stale teammate assignment. Closes debt 06ddcc2c8e4d."""
        import os
        from unittest import mock

        import worktree

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Auth", "in-progress", file_domain=["a.py"])],
            )
        )
        # Stale assignment from a prior teammate; no in-place marker present.
        worktree.story_assignment_path(self.smm_dir, "worktree-story-002").write_text(
            "story-002"
        )
        with mock.patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-002"}):
            result = commit_handling._resolve_story_id(self.smm_dir, "/proj", ["a.py"])
        self.assertEqual(result, "story-001")

    def test_in_place_env_not_teammate_shaped_falls_through(self):
        """A leaked XP_TEAMMATE_NAME that isn't teammate-shaped is not trusted
        even with a marker and an assignment file under that same name. The env
        leg routes through identity.in_place_teammate_name (the shared helper
        the gates use), which shape-checks before the marker read — so the four
        sites that consume this env var agree on what counts as a teammate."""
        import os
        from unittest import mock

        import worktree

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Auth", "in-progress", file_domain=["a.py"])],
            )
        )
        worktree.story_assignment_path(self.smm_dir, "explorer-9").write_text(
            "story-002"
        )
        worktree.in_place_marker_path(self.smm_dir, "explorer-9").touch()
        with mock.patch.dict(os.environ, {"XP_TEAMMATE_NAME": "explorer-9"}):
            result = commit_handling._resolve_story_id(self.smm_dir, "/proj", ["a.py"])
        self.assertEqual(result, "story-001")

    def test_in_place_env_fallback_inert_for_lead(self):
        """No XP_TEAMMATE_NAME (the lead's own commits) → no env Tier 1, so a
        single in-progress story still resolves via the normal heuristic."""
        import os
        from unittest import mock

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Auth", "in-progress", file_domain=["a.py"])],
            )
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            result = commit_handling._resolve_story_id(self.smm_dir, "/proj", ["a.py"])
        self.assertEqual(result, "story-001")

    def test_tier2_solo_single_in_progress(self):
        """Solo sprint with one in-progress story attributes to it."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    )
                ],
            )
        )
        result = commit_handling._resolve_story_id(
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
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["src/ui.py", "src/util.py"]
        )
        self.assertEqual(result, "story-002")

    def test_tier2_multi_way_tie_returns_none(self):
        """Multiple in-progress stories with identical overlap → None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py", "src/ui.py"]
        )
        self.assertIsNone(result)

    def test_tier2_solo_multiple_no_overlap_returns_none(self):
        """Multiple in-progress stories with no overlap returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py \u2014 layout"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["unrelated.py"]
        )
        self.assertIsNone(result)

    def test_tier3_no_sprint_returns_none(self):
        """No sprint.json returns None."""
        result = commit_handling._resolve_story_id(self.smm_dir, "/proj", ["setup.py"])
        self.assertIsNone(result)

    def test_tier3_no_in_progress_stories(self):
        """Sprint with no in-progress stories returns None."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "done",
                        file_domain=["scripts/auth.py \u2014 login"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertIsNone(result)

    def test_tier25_lone_closing_story_no_prefix(self):
        """Unprefixed commit attributes to the lone closing story.

        Story-cadence review fixes are committed during /xp-story-close while
        the (only) active story is `closing` — no story is in-progress. When
        the commit carries no [story-NNN] prefix (e.g. a conventional-commit
        message), attribute to the single in-motion story rather than dropping
        it from per-story metrics.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "E2E",
                        "closing",
                        file_domain=["src/e2e.ts — harness"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["tests/e2e/util.ts"],  # need not overlap the domain
            message="fix(e2e): make cropToPortrait aspect-agnostic",
        )
        self.assertEqual(result, "story-001")

    def test_tier25_lone_reviewing_story_no_prefix(self):
        """Unprefixed commit attributes to the lone reviewing story."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "E2E", "reviewing", file_domain=["src/e2e.ts — x"]),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["src/other.ts"], message="refactor: tidy"
        )
        self.assertEqual(result, "story-001")

    def test_tier25_skipped_for_nonstory_bracket_prefix(self):
        """A [sprint-*]/[release] tag stays sprint-level even mid-close.

        An explicit non-story bracket prefix signals cross-cutting work; do
        not attribute it to the lone closing story.
        """
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "E2E", "closing", file_domain=["src/e2e.ts — x"]),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj",
            ["scripts/e2e/env.sh"],
            message="[sprint-direct] fix(e2e): guard seed reset",
        )
        self.assertIsNone(result)

    def test_tier25_skipped_when_multiple_in_motion(self):
        """Two in-motion stories → ambiguous → None (aggregate at sprint)."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "A", "closing", file_domain=["src/a.ts — x"]),
                    _s("story-002", "B", "reviewing", file_domain=["src/b.ts — y"]),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["src/c.ts"], message="fix: shared tweak"
        )
        self.assertIsNone(result)

    def test_tier25_not_fired_when_story_in_progress(self):
        """In-progress story present → Tier 2 handles it, Tier 2.5 irrelevant."""
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "A", "closing", file_domain=["src/a.ts — x"]),
                    _s("story-002", "B", "in-progress", file_domain=["src/b.ts — y"]),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["src/b.ts"], message="fix: tweak b"
        )
        self.assertEqual(result, "story-002")

    def test_commit_metadata_includes_story_id(self):
        """Commit event metadata includes story_id when resolved."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-003")
        assignment.write_text("story-003")

        with patch_commits(files=["a.py"], body="Add feature", head_sha="def456"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add feature'",
                    stdout="[main def456] Add feature\n 1 file changed",
                    cwd="/proj/.claude/worktrees/worktree-story-003",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_ev), 1)
        self.assertEqual(commit_ev[0]["metadata"]["story_id"], "story-003")

    def test_commit_metadata_no_story_id_when_not_resolved(self):
        """Commit event metadata omits story_id when not resolved."""
        with patch_commits(files=["a.py"], body="Fix bug", head_sha="aaa111"):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main aaa111] Fix bug\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        commit_ev = events_of_type(events, EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_ev), 1)
        self.assertNotIn("story_id", commit_ev[0]["metadata"])

    def test_solo_agent_ignores_marker_uses_file_domain(self):
        """Solo agent (name=main) ignores .story-assignment-main, uses Tier 2."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "main")
        assignment.write_text("story-001")
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py — layout"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(self.smm_dir, "/proj", ["src/ui.py"])
        self.assertEqual(result, "story-002")

    def test_solo_agent_single_story_ignores_stale_marker(self):
        """Solo agent with one in-progress story ignores stale marker."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "main")
        assignment.write_text("story-old")
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir, "/proj", ["scripts/auth.py"]
        )
        self.assertEqual(result, "story-001")

    def test_teammate_still_reads_assignment_marker(self):
        """Teammates still use Tier 1 marker (regression guard)."""
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-001")
        assignment.write_text("story-001")
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "Auth",
                        "in-progress",
                        file_domain=["scripts/auth.py — login"],
                    ),
                    _s(
                        "story-002",
                        "UI",
                        "in-progress",
                        file_domain=["src/ui.py — layout"],
                    ),
                ]
            )
        )
        result = commit_handling._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/worktree-story-001",
            ["src/ui.py"],
        )
        self.assertEqual(result, "story-001")


if __name__ == "__main__":
    unittest.main()
