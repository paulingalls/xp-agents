#!/usr/bin/env python3
"""Tests for pre_tool_bash_commit_gates.py — the extracted commit-gate module.

story-011: pure move of the commit-gate block out of pre_tool_bash.py (496
lines, hard against the 500-line cap). The pre-existing ~19 commit-gate test
files keep exercising the same behaviour through `pre_tool_bash.run` — this
file adds what they don't cover:

- the new `commit_gate_parts` primitive, called directly (the old suite only
  ever reaches it through `run`);
- the MODULE BOUNDARY: the gates live here, not in pre_tool_bash.py;
- headroom on the line-count cap that caused this extraction;
- gate ORDERING. AC#4 requires each gate to block at the same point in the
  sequence as before, but the pre-existing suite pins gate *messages*, not
  their relative order. A silent reorder that moved the tier-1 scan after the
  review-cycle gate would pass every one of those tests while disabling
  security enforcement whenever a commit also lacked review coverage.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash_commit_gates
import sprint_store
import verify_deferred
from _close_fixtures import _assert_text_ordering
from conftest import _HookTestCase, make_sprint_dict, make_story_dict

_COMMIT_CMD = "git commit -m 'test'"

_AKIA_DIFF = (
    "diff --git a/src/cfg.py b/src/cfg.py\n"
    "--- a/src/cfg.py\n"
    "+++ b/src/cfg.py\n"
    "@@ -1,1 +1,2 @@\n"
    " existing\n"
    '+aws_key = "AKIAIOSFODNN7EXAMPLE"\n'
)

_OVER_THRESHOLD = ["a.py", "b.py", "c.py"]
_STAGED_COVERAGE_AE = {"type": "pytest", "command": "pytest tests/a.py tests/b.py"}

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


class TestCommitGatePartsPrimitive(_HookTestCase):
    """Behaviour of `commit_gate_parts`, called directly (not via `run`)."""

    @patch("git_commits.is_git_commit", return_value=False)
    def test_non_commit_returns_empty_list(self, *_mocks):
        result = pre_tool_bash_commit_gates.commit_gate_parts(
            self.smm_dir, "git status", "/tmp"
        )
        self.assertEqual(result, [])

    @patch("commits.get_staged_diff", return_value=_AKIA_DIFF)
    @patch("git_commits.is_git_commit", return_value=True)
    def test_tier1_secret_raises_blocked_error(self, *_mocks):
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, _COMMIT_CMD, "/tmp"
            )
        self.assertIn("aws-access-key", str(ctx.exception))


class TestModuleBoundary(_HookTestCase):
    """The commit gates live in the new module; pre_tool_bash.py holds none."""

    _GATE_MARKERS = (
        "Tier 1 security scan blocked this commit",
        "Run /xp-quality-review before committing",
        "staged_lint.staged_lint_gate",
        "branching.get_branching_stage",
    )

    def _read(self, name: str) -> str:
        return (_SCRIPTS_DIR / name).read_text()

    def test_pre_tool_bash_has_headroom_under_the_cap(self):
        """Not just under 500 — comfortably under, with room for the next
        edit. 'Just under' is what produced this debt four times already."""
        lines = self._read("pre_tool_bash.py").splitlines()
        self.assertLessEqual(
            len(lines),
            450,
            "pre_tool_bash.py should have real headroom after the "
            "commit-gate extraction, not just squeak under the cap",
        )

    def test_gate_markers_absent_from_pre_tool_bash(self):
        source = self._read("pre_tool_bash.py")
        for marker in self._GATE_MARKERS:
            self.assertNotIn(
                marker,
                source,
                f"commit-gate marker {marker!r} should have moved out of "
                "pre_tool_bash.py",
            )

    def test_gate_markers_present_in_new_module_non_vacuously(self):
        source = self._read("pre_tool_bash_commit_gates.py")
        for marker in self._GATE_MARKERS:
            self.assertIn(marker, source)
        # Non-vacuity: the file actually has substance, not an empty stub
        # that would trivially fail to contain any of the markers above.
        self.assertGreater(len(source), 1000)


class TestGateOrdering(_HookTestCase):
    """Gate ordering and short-circuit behaviour must be preserved exactly.

    The only ordering assertion anywhere in the pre-existing commit-gate suite
    is test_pre_tool_bash_git_c_target.py's
    TestTheBlockPreemptsEveryDownstreamGate — and that pins the dash-C refusal,
    not the gates below it. Nothing pins tier-1-before-review-cycle,
    staged-lint-before-review-cycle, or the advisory concatenation order.
    """

    @patch("commits.get_code_files_for_review", return_value=_OVER_THRESHOLD)
    @patch("commits.get_staged_diff", return_value=_AKIA_DIFF)
    @patch("git_commits.is_git_commit", return_value=True)
    def test_tier1_wins_over_unsatisfied_review_cycle(self, *_mocks):
        """A staged secret AND an unsatisfied review cycle together: the
        tier-1 message must win. A reorder that moved tier-1 later would
        instead surface the review-cycle message and let the secret land
        the moment review coverage was satisfied."""
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, _COMMIT_CMD, "/tmp"
            )
        msg = str(ctx.exception)
        self.assertIn("Tier 1 security scan blocked", msg)
        self.assertNotIn("/xp-quality-review", msg)

    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_staged_lint_runs_before_review_cycle_gate(self, *_mocks):
        order: list[str] = []

        def _lint(_staged, _cwd):
            order.append("lint")
            return []

        def _code_files(_cwd, *_a, **_kw):
            order.append("review")
            return _OVER_THRESHOLD

        with (
            patch("staged_lint.staged_lint_gate", side_effect=_lint),
            patch("commits.get_code_files_for_review", side_effect=_code_files),
            self.assertRaises(_common.BlockedError),
        ):
            pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, _COMMIT_CMD, "/tmp"
            )
        self.assertEqual(order, ["lint", "review"])

    @patch("verify_deferred.parse_verify_deferred", return_value=None)
    @patch("verify_deferred.untouched_paths_for_story", return_value=["tests/x.py"])
    @patch("identity.extract_story_id", return_value="story-001")
    @patch("commits.is_escape_hatch_commit", return_value=False)
    @patch("identity.get_current_branch", return_value="main")
    @patch("branching.is_protected_branch", return_value=True)
    @patch("branching.get_branching_stage", return_value=1)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("staged_lint.staged_lint_gate", return_value=["LINT ADVISORY"])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_advisory_concatenation_order(self, *_mocks):
        """staged-lint parts, then branch-guard parts, then the verify nudge —
        assert relative POSITIONS; a substring check alone cannot detect a
        reorder of the underlying `parts.extend`/`parts.append` calls."""
        parts = pre_tool_bash_commit_gates.commit_gate_parts(
            self.smm_dir, _COMMIT_CMD, "/tmp"
        )
        _assert_text_ordering(
            self,
            "\n\n".join(parts),
            "LINT ADVISORY",
            "story branch",
            "Verify-touch",
            msg="staged-lint, then branch-guard, then verify-touch nudge",
        )


class TestVerifyTouchNudgeStagedCoverage(_HookTestCase):
    """story-006 AC 1-3: the commit-time nudge counts staged files too.

    Mocks only the git log-walk boundary (`verify_paths._changed_files`) and
    `commits.get_staged_files` — the union logic in `untouched_verify_paths`
    (also_changed) runs for real, so a broken union shows up here, not just
    a mocked stand-in for it.
    """

    _STORY_BRANCH = "paul/story-001-feature"

    def _save_story(self):
        story = make_story_dict(id="story-001", status="in-progress")
        story["acceptance_criteria"] = ["a manual AC"]
        story["acceptance_execution"] = _STAGED_COVERAGE_AE
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _run(self, *, committed, staged):
        with (
            patch("branching.get_branching_stage", return_value=2),
            patch("branching.is_sprint_branch", return_value=False),
            patch("git_commits.is_git_commit", return_value=True),
            patch("commits.get_code_files_for_review", return_value=[]),
            patch("identity.get_current_branch", return_value=self._STORY_BRANCH),
            patch("branching.get_story_base_branch", return_value="base"),
            patch("verify_paths._changed_files", return_value=set(committed)),
            patch("commits.get_staged_files", return_value=sorted(staged)),
        ):
            return pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, _COMMIT_CMD, "/tmp"
            )

    def test_first_commit_with_every_path_staged_does_not_fire(self):
        # base == HEAD (nothing committed yet); every declared path sits
        # staged in the index. Regression for the fire-on-first-commit bug.
        self._save_story()
        parts = self._run(committed=set(), staged={"tests/a.py", "tests/b.py"})
        self.assertFalse(any("Verify-touch" in p for p in parts))

    def test_commit_touching_none_of_the_paths_still_fires_and_names_them(self):
        self._save_story()
        parts = self._run(committed=set(), staged={"other.py"})
        joined = "\n".join(parts)
        self.assertIn("Verify-touch", joined)
        self.assertIn("tests/a.py", joined)
        self.assertIn("tests/b.py", joined)

    def test_union_of_committed_and_staged_coverage_does_not_fire(self):
        self._save_story()
        parts = self._run(committed={"tests/a.py"}, staged={"tests/b.py"})
        self.assertFalse(any("Verify-touch" in p for p in parts))

    def test_partial_staged_coverage_still_fires_for_the_rest(self):
        # Staged coverage widens the set; it must not blanket-clear it.
        self._save_story()
        parts = self._run(committed=set(), staged={"tests/a.py"})
        joined = "\n".join(parts)
        self.assertIn("Verify-touch", joined)
        self.assertIn("tests/b.py", joined)
        nudge = next(p for p in parts if "Verify-touch" in p)
        self.assertNotIn("tests/a.py", nudge)


class TestCloseGateIgnoresStagedCoverage(_HookTestCase):
    """Pins `verify_deferred.untouched_paths_for_story`'s no-`staged` default
    to commit-only coverage — story-006's most load-bearing test even though
    no AC names it directly.

    By this module's naming logic this test belongs beside `verify_deferred`,
    not the commit gate. It lives here anyway, to avoid a third sprint
    file_domain amendment (story-006 already added two). Do not "tidy" it
    into a verify_deferred test module without also moving it consciously —
    it is what stops a future "just make staged the default" from letting a
    story merge with its acceptance test staged and never committed: the
    close gate and the story-close preload CLI both call this function
    without `staged`, so its default must stay commit-only forever.
    """

    def test_close_gate_default_ignores_the_index(self):
        story = make_story_dict(id="story-001", status="in-progress")
        story["acceptance_criteria"] = ["a manual AC"]
        story["acceptance_execution"] = {
            "type": "pytest",
            "command": "pytest tests/a.py",
        }
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

        with (
            patch("branching.get_story_base_branch", return_value="base"),
            patch("verify_paths._changed_files", return_value=set()),
        ):
            untouched = verify_deferred.untouched_paths_for_story(
                self.smm_dir, "/tmp", "story-001"
            )
        self.assertEqual(untouched, ["tests/a.py"])


if __name__ == "__main__":
    unittest.main()
