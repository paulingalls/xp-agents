#!/usr/bin/env python3
"""Integration tests for the /xp-story-close skill.

Mirrors test_sprint_close.py / test_plan_close.py. story-close merges a
single story branch into the sprint base (TARGET_BRANCH = story-base
from branching.py get-base — the sprint branch at stage 2+, primary
otherwise). Built on close_common.py from day one.

Solo-only JIT-next: after the merge, story-close picks the next
in-progress story whose deps are done (sprint_cli.py next-in-progress)
and creates its branch off the merged tip — but only if the story has
no branch_name yet in sprint.json. Teammate-mode parallel branches
(all created up-front at /xp-assign) already have branch_name set,
so JIT-next is a no-op for them.

Worktree cleanup for teammate stories lands in commit 10 (a separate
focused commit).
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    get_current_branch_at,
    seed_sprint_with_stories,
    write_system_context,
)
from _close_fixtures import _ClosePreloadCommonTests, _CloseSkillTextCommonTests
from conftest import _extract_preload_var, _IntegrationTestCase


class TestStoryClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the five fields the close skill needs.

    TARGET_BRANCH = story base (sprint branch at stage 2+, primary
    otherwise) — the merge destination for a story branch.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_via_get_base(self):
        write_system_context(self.smm_dir, stage=2)
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        # branching.py get-base returns the story base — sprint branch
        # at stage 2+ (none recorded yet here so falls through to
        # primary). check=True so a broken branching.py doesn't yield
        # "" == "" false-green.
        expected = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "get-base",
                "--cwd",
                str(self.tmpdir),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(expected, "", "branching.py get-base must resolve")
        self.assertEqual(_extract_preload_var(result.stdout, "TARGET_BRANCH"), expected)


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md"


class TestStoryClosePreloadTeammateDetection(_IntegrationTestCase):
    """Story-close preload emits TEAMMATE_CWD + overrides CURRENT_BRANCH
    when a teammate worktree corresponds to the just-done story.

    Implicit-derivation discovery (story-002 sprint-057): no marker, no
    /xp-accept context-passing — preload pairs live teammate worktrees
    against sprint.json status, picks the worktree whose story is
    `done`. Solo flow (no teammate worktree, or no matching done story)
    keeps the orchestrator HEAD as CURRENT_BRANCH and TEAMMATE_CWD="".
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def _create_worktree(self, story_id):
        sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
        import spawn_teammate

        name = f"worktree-{story_id}"
        return spawn_teammate.create_worktree(name, str(self.tmpdir))

    def test_solo_emits_empty_teammate_cwd_and_orchestrator_branch(self):
        # No teammate worktree at all — solo flow.
        seed_sprint_with_stories(self.smm_dir, [("story-001", "reviewing")])
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "TEAMMATE_CWD"), "")
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"),
            get_current_branch_at(self.tmpdir),
        )

    def test_reviewing_teammate_emits_teammate_cwd_and_teammate_branch(self):
        # Close-then-done: story is in `reviewing` while /xp-story-close
        # runs (mark-done is the FINAL step after merge).
        wt_path = self._create_worktree("story-042")
        seed_sprint_with_stories(self.smm_dir, [("story-042", "reviewing")])
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = _extract_preload_var(result.stdout, "TEAMMATE_CWD")
        self.assertEqual(emitted, str(Path(wt_path).resolve()))
        # Teammate branch (not orchestrator's) — branching.create_worktree
        # checks out a branch named after the worktree (worktree-story-042).
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"),
            "worktree-story-042",
        )

    def test_in_progress_teammate_emits_empty_teammate_cwd(self):
        # Worktree exists but story is in-progress, not reviewing — preload
        # should NOT pick it; CURRENT_BRANCH stays at orchestrator HEAD.
        self._create_worktree("story-007")
        seed_sprint_with_stories(self.smm_dir, [("story-007", "in-progress")])
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "TEAMMATE_CWD"), "")
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"),
            get_current_branch_at(self.tmpdir),
        )

    def test_multi_reviewing_match_propagates_failure(self):
        # The helper's "fail loud on multi-match" contract only holds if
        # the preload doesn't swallow it. Two `reviewing` stories with live
        # worktrees signal broken /xp-accept iteration — the preload
        # MUST surface the helper's stderr and exit non-zero rather than
        # silently degrading to solo flow (which would then dispatch
        # close_common.py at the orchestrator cwd against the wrong
        # branch). Regression guard for the original `2>/dev/null || echo ""`.
        self._create_worktree("story-101")
        self._create_worktree("story-102")
        seed_sprint_with_stories(
            self.smm_dir, [("story-101", "reviewing"), ("story-102", "reviewing")]
        )
        result = self._run_preload(self._PRELOAD)
        self.assertNotEqual(
            result.returncode,
            0,
            "preload must propagate multi-match ValueError, not swallow it",
        )
        self.assertIn("multiple reviewing stories", result.stderr)


class TestStoryCloseSkillText(_CloseSkillTextCommonTests, unittest.TestCase):
    """Story-close SKILL.md guard tests.

    Inherits the close-skill family contract from
    _CloseSkillTextCommonTests: invokes close_common.py's four
    subcommands, forks the close-reviewer in story mode, asks before
    merging. Adds story-specific tests: forks reviewer in story mode,
    auto-resolves LIKELY ADDRESSED concerns (per recorded policy:
    story+sprint YES, plan+free NO), and gates JIT-next dispatch on
    next-in-progress + branch_name absence.
    """

    _SKILL_MD = _SKILL_MD
    _MODE = "story"

    def test_forks_close_reviewer_in_story_mode(self):
        # The mode literal must appear under the ## Mode prompt section
        # so the close-reviewer routes to its story-mode focus.
        self.assertIn("## Mode\\nstory", self.text)

    def test_auto_resolves_likely_addressed_concerns(self):
        # Story-close runs the same Step 5b pattern as sprint-close —
        # per recorded policy, story+sprint auto-resolve, plan+free do
        # not. Pin the triage_preload + work_selection_decide tools.
        self.assertIn("triage_preload.py", self.text)
        self.assertIn("triage-drop", self.text)
        self.assertIn("LIKELY ADDRESSED", self.text)

    def test_dispatches_jit_next_after_merge(self):
        # JIT-next dispatch must invoke sprint_cli.py next-in-progress
        # AFTER close_common.py merge (so the merge tip is the new
        # branch base) and must check the story's branch_name in
        # sprint.json before creating (parallel teammate branches
        # already exist).
        merge_match = re.search(r"close_common\.py\s+merge", self.text)
        assert merge_match is not None
        # Find the next-in-progress invocation specifically. Anchoring
        # on the literal subcommand avoids matching the allowed-tools
        # frontmatter line that mentions sprint_cli.py without the
        # subcommand.
        next_idx = self.text.find("next-in-progress")
        self.assertNotEqual(
            next_idx,
            -1,
            "SKILL.md must invoke sprint_cli.py next-in-progress for JIT-next dispatch",
        )
        # Must be the bash invocation, not just a prose mention.
        self.assertIn("sprint_cli.py", self.text)
        self.assertLess(
            merge_match.start(),
            next_idx,
            "next-in-progress dispatch must appear AFTER close_common.py merge",
        )

    def test_jit_next_skips_when_branch_already_set(self):
        # The skill must read sprint.json (or query sprint_cli) for the
        # candidate's branch_name and skip JIT-create when it's already
        # set — that means the branch exists (parallel teammate batch
        # at /xp-assign), creating it again would clobber.
        self.assertRegex(
            self.text,
            r"branch_name",
            "SKILL.md must reference branch_name to gate JIT-create",
        )

    def test_jit_next_uses_explicit_shell_guard(self):
        # Pin the explicit `if NEXT_STORY=$(...)` outer guard and the
        # inner `if [ -z "$NEXT_BRANCH" ]; then` so the gate is shell-
        # enforced, not just prose. A regression that drops the
        # explicit if/then would let an LLM-orchestrator interpret the
        # `&&`-style guard incorrectly and run JIT-create even when
        # `next-in-progress` exited non-zero.
        self.assertRegex(
            self.text,
            r"if NEXT_STORY=\$\(",
            "JIT-next dispatch must use an explicit `if NEXT_STORY=$(...)` "
            "outer guard so non-zero exit short-circuits cleanly",
        )
        self.assertRegex(
            self.text,
            r'if \[ -z "\$NEXT_BRANCH" \]; then',
            "JIT-create must run inside an explicit `if [ -z $NEXT_BRANCH ]; "
            "then` block so parallel-teammate branches are skipped, not "
            "clobbered by a fresh create",
        )

    def test_jit_next_falls_back_to_scheduled_when_no_in_progress(self):
        # Under the four-state lifecycle (commit 1+2+3 of this work),
        # solo mode's next story is in `scheduled` status — xp-assign
        # only promoted the FIRST scheduled at /xp-assign time. The
        # JIT-next dispatch must look at next-scheduled when
        # next-in-progress is empty, promote it to in-progress, and
        # create the branch off the merged sprint tip.
        self.assertIn(
            "next-scheduled",
            self.text,
            "JIT-next dispatch must check next-scheduled for the solo "
            "fallback (the next scheduled story becomes the new in-progress)",
        )
        # The promotion step (update-story <id> in-progress) must be
        # explicit in the SKILL.md so a future editor doesn't drop it
        # and leave the next story stuck in scheduled forever.
        self.assertIn(
            "update-story",
            self.text,
            "SKILL.md must promote scheduled → in-progress before creating the branch",
        )

    def test_cleans_up_teammate_worktree_when_present(self):
        # Per-story symmetry (decision 9029c07ae198): cleanup_teammate.py
        # runs from /xp-story-close per closed story when a teammate
        # worktree existed for that story — not bulk-after-loop in
        # /xp-accept. SKILL.md must reference cleanup_teammate.py and
        # gate the call on worktree existence (so solo-mode closes
        # don't try to clean up a non-existent worktree).
        self.assertIn(
            "cleanup_teammate.py",
            self.text,
            "/xp-story-close must invoke cleanup_teammate.py for the "
            "just-closed story when a teammate worktree existed for it",
        )
        # Gate prose must mention worktree presence (e.g. "if a worktree
        # exists" / "teammate worktree" / "worktree-story-") so solo
        # closes skip the cleanup cleanly.
        self.assertRegex(
            self.text,
            r"(?is)worktree[^.\n]{0,200}exist|worktree-story-",
            "SKILL.md must gate cleanup_teammate.py on worktree presence",
        )
        # Pin the actual worktree-name pattern. Teammate worktrees are
        # `worktree-story-NNN` with NO slug suffix (see spawn_teammate.py
        # and identity._TEAMMATE_PREFIX). A grep that requires a trailing
        # hyphen (e.g. `^worktree-story-NNN-`) would never match a real
        # teammate worktree and the cleanup would silently no-op.
        self.assertNotRegex(
            self.text,
            r'grep[^\n]*"\^worktree-\$\{STORY_ID\}-"',
            "Worktree-grep must not require a trailing hyphen — teammate "
            "worktrees are named `worktree-story-NNN` exactly, no slug "
            "suffix (spawn_teammate.py, identity._TEAMMATE_PREFIX).",
        )

    def test_does_not_dispatch_sprint_review(self):
        # Per recorded decision e30e9e91e61a: /xp-story-close NEVER
        # fires /xp-sprint-review. /xp-accept owns that single
        # dispatch after its loop completes. Catches the regression
        # where someone adds the /xp-sprint-review chain here.
        self.assertNotIn(
            "/xp-sprint-review",
            self.text,
            "/xp-story-close must NOT invoke /xp-sprint-review — "
            "/xp-accept owns the single sprint-review dispatch after "
            "its loop completes (decision e30e9e91e61a)",
        )

    def test_steps_1_2_3_use_teammate_cwd_token_but_step_7_does_not(self):
        # Story-002 sprint-057 (corrected by story-003 capstone):
        # preflight/push/create-pr route at the teammate worktree
        # (`${TEAMMATE_CWD:-.}`). Merge does NOT — `git merge` checks
        # out the target branch which is held by the orchestrator's
        # worktree; routing merge at TEAMMATE_CWD fails with
        # "'<target>' is already used by worktree" (caught by capstone).
        self.assertIn(
            "${TEAMMATE_CWD:-.}",
            self.text,
            "SKILL.md must route close_common.py at ${TEAMMATE_CWD:-.} so "
            "teammate close ops run from the worktree (story-002 sprint-057).",
        )
        # Pin: preflight/push/create-pr MUST use the token (DOTALL since
        # the token sits on the line after the subcommand).
        for subcmd in ("preflight", "push", "create-pr"):
            self.assertRegex(
                self.text,
                rf"(?s)close_common\.py\s+{re.escape(subcmd)}[\s\S]*?\$\{{TEAMMATE_CWD:-\.\}}",
                f"close_common.py {subcmd} must route at ${{TEAMMATE_CWD:-.}}",
            )
        # Inverse pin for merge: must NOT route at TEAMMATE_CWD (always
        # orchestrator cwd because merge checks out target).
        self.assertNotRegex(
            self.text,
            r"(?s)close_common\.py\s+merge[\s\S]*?\$\{TEAMMATE_CWD:-\.\}",
            "close_common.py merge must run at orchestrator cwd (--cwd .); "
            "git merge checks out target branch held by orchestrator worktree.",
        )
        self.assertRegex(
            self.text,
            r"(?s)close_common\.py\s+merge[\s\S]*?--cwd\s+\.",
            "close_common.py merge must explicitly use --cwd .",
        )

    def test_skill_documents_teammate_cwd_semantics(self):
        # Future editors must see why TEAMMATE_CWD exists. The SKILL.md
        # MUST explain (a) when it's set and (b) which steps consume it.
        self.assertIn(
            "TEAMMATE_CWD",
            self.text,
            "SKILL.md must document TEAMMATE_CWD's purpose and lifecycle",
        )


if __name__ == "__main__":
    unittest.main()
