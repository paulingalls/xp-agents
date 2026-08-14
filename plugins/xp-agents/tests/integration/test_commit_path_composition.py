#!/usr/bin/env python3
"""The commit path's entry condition, driven end to end on a real repo.

`is_git_commit` is the ENTRY CONDITION for both the PreToolUse gate stack and
the PostToolUse commit-event path, so what it admits decides what every gate
below it ever sees. Story-001 narrowed it; this file pins the narrowing at the
two places no sibling suite reaches.

What is here, and why it is not covered elsewhere:

* The PRE-tool leg, unmocked. `test_merge_abort_ungated.py` drives the same gate
  in-process with `get_code_files_for_review` patched and a plain `-m` commit.
  Here the staged files are real, the hook is a subprocess, and the command is
  the stdin-heredoc form an agent actually writes.
* An abort recording NO commit event. Nothing else asserts that negative, and
  the rebuild path is what makes it non-obvious: it reaches a fresh HEAD without
  needing the command to have produced it.

What is deliberately NOT here: the post-tool recovery of a heredoc message.
`test_heredoc_commit_event.py` drives the same hook over the same command and
goes red on both the classifier narrowing and the recovery regression —
measured, not assumed. A copy of it here would be a test that cannot fail alone.

Scoped to two fixes, not three. Story-002's coordination write shares no seam
with this path: `update_coordination` is called only from the PostToolUse
`Write|Edit|MultiEdit` hook, and `bash_post_tool.py` references coordination
zero times. An assertion about it here would pass with story-002 reverted.

The sharp edge is the pre-tool case: below the review threshold the gate exits 0
whether or not `is_git_commit` saw a commit, so asserting admission proves
nothing. Only a BLOCK discriminates.

Nothing is mocked. The hooks run as subprocesses against a real repo, so the
tier-1 secret scan and staged-lint gate run for real against the staged bytes —
staged content is kept trivial and secret-free so a block can only come from the
review gate, and a temp repo has no linter config so the lint leg skips.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from _repo_fixtures import git_in, init_nested_repo
from conftest import _IntegrationTestCase
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT

# The stdin-heredoc form, body and all: the classifier has to reach past a
# message the shell hands to git as data before it can answer at all.
_BODY = (
    "Render the attribution suffix once\n\n"
    'Verified with pytest -m "slow" before landing.'
)
_HEREDOC_COMMIT = f"git commit -F - <<'MSG'\n{_BODY}\nMSG"


class TestTheCommitPathEntryCondition(_IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.repo = init_nested_repo(self.tmpdir)
        # Pinned, not inherited: the block below exists only under commit
        # cadence, and a suite that leans on `read_review_cadence`'s default
        # stops testing a block the moment that default changes.
        markers.write_review_cadence(self.smm_dir, "commit")

    def _git(self, *args: str, stdin: str | None = None) -> str:
        return git_in(self.repo, *args, stdin=stdin)

    def _arm_the_review_gate(self) -> None:
        """Stage enough real code files that the review-cycle gate blocks.

        Real files, not a patched count — nothing is mocked on this route.
        Content is trivial and secret-free so the tier-1 scan cannot block for a
        reason this test is not about.
        """
        src = self.repo / "src"
        src.mkdir(exist_ok=True)
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (src / name).write_text("x = 1\n")
        self._git("add", "-A")

    def _run_hook(self, script: str, command: str) -> subprocess.CompletedProcess:
        return self._run_script(
            script,
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "tool_response": {"stdout": "", "stderr": ""},
                "cwd": str(self.repo),
                "agent_id": "main",
            },
            cwd=self.repo,
        )

    def _commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    # -- The pre-tool leg ----------------------------------------------------

    def test_a_heredoc_commit_is_routed_into_the_gate_stack(self):
        """A BLOCK is the proof, not an admission.

        Below the review threshold the gate exits 0 whether or not
        `is_git_commit` saw a commit, so asserting admission would pass with
        story-001 reverted. Blocking requires the classifier to have routed this
        command into the gate stack in the first place.
        """
        self._arm_the_review_gate()

        result = self._run_hook("pre_tool_bash.py", _HEREDOC_COMMIT)

        self.assertEqual(result.returncode, 2, f"expected a block: {result.stderr}")
        # Name the gate. The tier-1 secret scan and the unresolvable-target
        # refusal also exit 2, and a bare "review" substring is one reworded
        # message away from matching either of them instead.
        self.assertIn("/xp-quality-review", result.stderr)

    def test_a_non_commit_is_not_routed_into_the_gate_stack(self):
        """The contrast that makes the block above meaningful: the same armed
        gate lets a `git merge --abort` straight through, because story-001
        stopped classifying it as commit-producing."""
        self._arm_the_review_gate()

        result = self._run_hook("pre_tool_bash.py", "git merge --abort")

        self.assertEqual(result.returncode, 0, result.stderr)

    # -- The post-tool leg ---------------------------------------------------

    def test_an_abort_claims_no_commit(self):
        """It produced no commit, so nothing may record one.

        The COUNT, not a property of whatever happens to be recorded: with the
        non-committing subtraction reverted, the abort reaches the rebuild path,
        which finds the fresh HEAD this setup just made and records an event for
        a commit the command did not produce.
        """
        (self.repo / "src").mkdir(exist_ok=True)
        (self.repo / "src" / "delta.py").write_text("x = 1\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "work that is already recorded")

        result = self._run_hook("bash_post_tool.py", "git merge --abort")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertEqual(self._commit_events(), [], "an abort recorded a commit")


if __name__ == "__main__":
    unittest.main()
