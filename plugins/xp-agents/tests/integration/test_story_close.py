#!/usr/bin/env python3
"""Integration tests for the /xp-story-close skill.

Mirrors test_sprint_close.py / test_plan_close.py. story-close merges a
single story branch into the sprint base (TARGET_BRANCH = story-base
from branching.py get-base — the sprint branch at stage 2+, primary
otherwise). Built on close_common.py from day one.

As of story-006, frontier promotion moved to /xp-schedule: story-close
merges + cleans up only, and /xp-accept's post-loop owns the next
dispatch (it invokes /xp-schedule). Close no longer promotes or
branches the next story.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    get_current_branch_at,
    make_commit,
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


class TestStoryCloseVerifyGate(_IntegrationTestCase):
    """Preload computes the verify-touch gate (story-003 / Milestone 5).

    On a story branch ahead of its base, the preload runs the verify_paths
    CLI and emits VERIFY_UNTOUCHED (declared acceptance-test paths no commit
    on base..HEAD touched) + VERIFY_DEFERRED (whether a [verify-deferred]
    commit is in the branch history). The SKILL refuses on
    untouched && !deferred.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def _seed_story(self, verify_command: str, story_id: str = "story-001") -> None:
        story = {
            "id": story_id,
            "title": "t",
            "status": "closing",
            "dependencies": [],
            "milestone_ref": "",
            "design_sources": "",
            "context": "",
            "file_domain": [],
            "interface_contracts": [],
            "acceptance_criteria": [],
            "acceptance_execution": {"type": "pytest", "command": verify_command},
        }
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                {
                    "sprint_id": "sprint-001",
                    "goal": "g",
                    "started": "2026-05-21",
                    "milestone": "",
                    "stories": [story],
                }
            )
        )

    def _story_branch(self, branch: str, filename: str, message: str) -> None:
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        make_commit(str(self.tmpdir), branch, filename, "x", message)

    def test_untouched_path_emits_gate_fields(self):
        write_system_context(self.smm_dir, stage=2, integration_branch="main")
        self._seed_story("pytest acc_test.py")
        # Commit touches an unrelated file — acc_test.py stays untouched.
        self._story_branch("u/story-001-a", "other.py", "wip")
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "VERIFY_UNTOUCHED"), "acc_test.py"
        )
        self.assertEqual(
            _extract_preload_var(result.stdout, "VERIFY_DEFERRED"), "false"
        )

    def test_touched_path_emits_empty_untouched(self):
        write_system_context(self.smm_dir, stage=2, integration_branch="main")
        self._seed_story("pytest acc_test.py")
        self._story_branch("u/story-001-b", "acc_test.py", "add acceptance test")
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_UNTOUCHED"), "")
        self.assertEqual(
            _extract_preload_var(result.stdout, "VERIFY_DEFERRED"), "false"
        )

    def test_verify_deferred_commit_sets_deferred_true(self):
        write_system_context(self.smm_dir, stage=2, integration_branch="main")
        self._seed_story("pytest acc_test.py")
        # Path still untouched, but a [verify-deferred] commit is in history.
        self._story_branch(
            "u/story-001-c", "other.py", "[verify-deferred] shipping under deadline"
        )
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "VERIFY_UNTOUCHED"), "acc_test.py"
        )
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_DEFERRED"), "true")

    def test_gate_scans_teammate_worktree_not_orchestrator_cwd(self):
        # The gate routes verify_paths + git-log at ${TEAMMATE_CWD:-.}.
        # Touch the verify path INSIDE the teammate worktree: the gate must
        # see it (untouched empty). A regression routing at the orchestrator
        # cwd (still on the sprint base, no touch) would report acc_test.py.
        sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
        import spawn_teammate

        wt_path = spawn_teammate.create_worktree("worktree-story-042", str(self.tmpdir))
        write_system_context(self.smm_dir, stage=2, integration_branch="main")
        self._seed_story("pytest acc_test.py", story_id="story-042")
        (Path(wt_path) / "acc_test.py").write_text("x")
        for args in (["add", "acc_test.py"], ["commit", "-m", "add acceptance test"]):
            subprocess.run(
                ["git", "-C", wt_path, *args], capture_output=True, check=True
            )
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_UNTOUCHED"), "")


class TestStoryClosePreloadTeammateDetection(_IntegrationTestCase):
    """Story-close preload emits TEAMMATE_CWD + overrides CURRENT_BRANCH
    when a teammate worktree corresponds to the in-closing story.

    Implicit-derivation discovery: no marker, no /xp-accept context-
    passing — preload pairs live teammate worktrees against sprint.json
    status, picks the worktree whose story is `closing` (the singleton
    in-pipeline lock; mark-done is the FINAL step after merge). Solo
    flow (no teammate worktree, or no matching closing story) keeps the
    orchestrator HEAD as CURRENT_BRANCH and TEAMMATE_CWD="".
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"

    def _create_worktree(self, story_id):
        sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
        import spawn_teammate

        name = f"worktree-{story_id}"
        return spawn_teammate.create_worktree(name, str(self.tmpdir))

    def test_solo_emits_empty_teammate_cwd_and_orchestrator_branch(self):
        # No teammate worktree at all — solo flow.
        seed_sprint_with_stories(self.smm_dir, [("story-001", "closing")])
        result = self._run_preload(self._PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "TEAMMATE_CWD"), "")
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"),
            get_current_branch_at(self.tmpdir),
        )

    def test_closing_teammate_emits_teammate_cwd_and_teammate_branch(self):
        # Story is in `closing` while /xp-story-close runs (xp-accept
        # promotes reviewing→closing before dispatch; mark-done is the
        # FINAL step after merge).
        wt_path = self._create_worktree("story-042")
        seed_sprint_with_stories(self.smm_dir, [("story-042", "closing")])
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
        # Worktree exists but story is in-progress, not closing — preload
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

    def test_multi_closing_match_propagates_failure(self):
        # The helper's "fail loud on multi-match" contract only holds if
        # the preload doesn't swallow it. Two `closing` stories with live
        # worktrees signal broken /xp-accept iteration — closing is the
        # singleton lock. Preload MUST surface the helper's stderr and
        # exit non-zero rather than silently degrading to solo flow
        # (which would then dispatch close_common.py at the orchestrator
        # cwd against the wrong branch). Regression guard for the
        # original `2>/dev/null || echo ""`.
        self._create_worktree("story-101")
        self._create_worktree("story-102")
        seed_sprint_with_stories(
            self.smm_dir, [("story-101", "closing"), ("story-102", "closing")]
        )
        result = self._run_preload(self._PRELOAD)
        self.assertNotEqual(
            result.returncode,
            0,
            "preload must propagate multi-match ValueError, not swallow it",
        )
        self.assertIn("multiple closing stories", result.stderr)


class TestStoryCloseSkillText(_CloseSkillTextCommonTests, unittest.TestCase):
    """Story-close SKILL.md guard tests.

    Inherits the close-skill family contract from
    _CloseSkillTextCommonTests: invokes close_common.py's four
    subcommands, forks the close-reviewer in story mode, asks before
    merging. Adds story-specific tests: forks reviewer in story mode,
    auto-resolves MAYBE ADDRESSED concerns (per recorded policy:
    story+sprint YES, plan+free NO). As of story-006, close no longer
    promotes/branches the next story — /xp-schedule owns that.
    """

    _SKILL_MD = _SKILL_MD
    _MODE = "story"

    def test_forks_close_reviewer_in_story_mode(self):
        # The mode literal must appear under the ## Mode prompt section
        # so the close-reviewer routes to its story-mode focus.
        self.assertIn("## Mode\\nstory", self.text)

    def test_auto_resolves_maybe_addressed_concerns(self):
        # Story-close runs the same Step 5b pattern as sprint-close —
        # per recorded policy, story+sprint auto-resolve, plan+free do
        # not. Pin the triage_preload + work_selection_decide tools.
        self.assertIn("triage_preload.py", self.text)
        self.assertIn("triage-drop", self.text)
        self.assertIn("MAYBE ADDRESSED", self.text)

    def test_close_does_not_promote_or_branch_next(self):
        # story-006 moved frontier promotion to /xp-schedule. Close now
        # merges + cleans up only — the JIT-next promote/branch dispatch is
        # gone, and /xp-accept's post-loop owns the next dispatch (it invokes
        # /xp-schedule off the merged tip). Guard against a regression that
        # re-adds in-skill promotion (which would double-promote alongside
        # /xp-schedule).
        for removed in ("next-in-progress", "next-scheduled", "JIT-next"):
            self.assertNotIn(
                removed,
                self.text,
                f"story-close must no longer reference {removed!r} — "
                "/xp-schedule owns frontier promotion now",
            )
        self.assertIn(
            "/xp-schedule",
            self.text,
            "story-close must document that the next frontier is promoted by "
            "/xp-schedule (via /xp-accept's post-loop), not by close",
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

    def test_verify_touch_gate_refuses_before_push(self):
        # story-003: the close must refuse when the story declares verify
        # paths no commit touched, naming them, unless [verify-deferred] is
        # in history. Pin the refuse message + both gate fields, and that
        # the gate is read BEFORE the push step (refuse early, no PR/merge).
        self.assertIn("no commit touched", self.text)
        self.assertIn("VERIFY_UNTOUCHED", self.text)
        self.assertIn("VERIFY_DEFERRED", self.text)
        gate_idx = self.text.find("VERIFY_UNTOUCHED")
        push_match = re.search(r"close_common\.py\s+push", self.text)
        assert push_match is not None
        self.assertLess(
            gate_idx,
            push_match.start(),
            "verify-touch gate must be evaluated before the push step",
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

    def test_preflight_createpr_use_teammate_cwd_push_relocates_merge_does_not(self):
        # preflight/create-pr route at the teammate worktree
        # (`${TEAMMATE_CWD:-.}`) — they read the story's diff/PR base.
        # PUSH does NOT: it relocates to the MAIN checkout (`--cwd .` +
        # `--smm-dir`). Pushing from the teammate worktree fires the project's
        # pre-push hook THERE, where a fresh worktree has no installed deps
        # → ERR_MODULE_NOT_FOUND. close_common.py detaches the main checkout
        # onto the story tip and pushes from there (deps present). Merge ALSO
        # runs at orchestrator cwd — `git merge` checks out the target branch
        # held by the orchestrator worktree.
        self.assertIn(
            "${TEAMMATE_CWD:-.}",
            self.text,
            "SKILL.md must route preflight/create-pr at ${TEAMMATE_CWD:-.} so "
            "those teammate ops run from the worktree (story-002 sprint-057).",
        )
        # Pin: preflight/create-pr MUST use the token (DOTALL since the token
        # sits on the line after the subcommand).
        for subcmd in ("preflight", "create-pr"):
            self.assertRegex(
                self.text,
                rf"(?s)close_common\.py\s+{re.escape(subcmd)}[\s\S]*?\$\{{TEAMMATE_CWD:-\.\}}",
                f"close_common.py {subcmd} must route at ${{TEAMMATE_CWD:-.}}",
            )
        # Push relocates to the main checkout: --cwd . (NOT TEAMMATE_CWD) and
        # passes --smm-dir so the relocate can resolve the story base ref.
        self.assertRegex(
            self.text,
            r"close_common\.py\s+push[^\n]*\n\s*--cwd\s+\.",
            "close_common.py push must relocate to the main checkout (--cwd .) "
            "so the pre-push hook runs with the main checkout's deps, not the "
            "depsless teammate worktree.",
        )
        self.assertRegex(
            self.text,
            r"close_common\.py\s+push[\s\S]{0,160}?--smm-dir",
            "close_common.py push must pass --smm-dir so the relocate can "
            "resolve the story base ref.",
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
