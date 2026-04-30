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

from _branching_fixtures import write_system_context
from _close_fixtures import _ClosePreloadCommonTests, _CloseSkillTextCommonTests
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent


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


if __name__ == "__main__":
    unittest.main()
