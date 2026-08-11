#!/usr/bin/env python3
"""The capstone: story-001's classifier and story-003's recovery, composing.

Each shipped green alone. They share a seam neither suite touches:
`is_git_commit` is the ENTRY CONDITION for the PostToolUse path
(`bash_post_tool.py:173`), and `recover_commit_message` runs ON that path. So a
narrowing that is correct in isolation can stop the recovery from ever being
reached, and both sibling suites stay green while it does. That is what this
file is for — not "is each right" but "does one real commit still traverse
both".

SCOPED TO TWO FIXES, NOT THREE. This was planned as a three-fix capstone
including story-002's coordination write. There is no such seam:
`update_coordination` is called only from `post_tool_use.py:88`, registered on
PostToolUse `Write|Edit|MultiEdit`; `bash_post_tool.py` references coordination
zero times and `pre_tool_bash.py` documents having no coordination gate. An
assertion about the coordination file here would pass with story-002 reverted,
and in a checkout where story-002 never happened.

EVERY ASSERTION HERE MUST BE ABLE TO FAIL, and that is not rhetorical — the plan
for this file contained two vacuous assertions before review caught them. The
sharp edge is Case 1: asserting the gate ADMITS the command proves nothing,
because below the review threshold it exits 0 whether or not the classifier saw
a commit at all. Only a BLOCK discriminates.

Nothing is mocked. The hooks run as subprocesses against a real repo, so the
tier-1 secret scan and staged-lint gate run for real against the staged bytes —
staged content is kept trivial and secret-free so a block can only come from the
review gate, and a temp repo has no linter config so the lint leg skips.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _IntegrationTestCase
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT

_SUBJECT = "Render the attribution suffix once"
# The token story-003 stopped from hijacking the message. Ordinary prose.
_BODY = f'{_SUBJECT}\n\nVerified with pytest -m "slow" before landing.'
_HEREDOC_COMMIT = f"git commit -F - <<'MSG'\n{_BODY}\nMSG"


class TestTheCommitPathComposes(_IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmpdir / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "-b", "main", ".")
        self._git("config", "user.email", "t@t.com")
        self._git("config", "user.name", "T")
        (self.repo / "README.md").write_text("init")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "init")
        # Commit cadence, written into THIS test's SMM dir: the ambient cadence
        # on disk is `story`, which only advises, and an advisory cannot arm the
        # block Case 1 needs.
        markers.write_review_cadence(self.smm_dir, "commit")

    def _git(self, *args: str, stdin: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            input=stdin,
        )
        if result.returncode != 0:
            raise AssertionError(f"git {args!r} failed: {result.stderr}")
        return result.stdout.strip()

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
        payload = {
            "session_id": "int-test",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "stderr": ""},
            "cwd": str(self.repo),
            "agent_id": "main",
        }
        return subprocess.run(
            ["python3", str(self.scripts_dir / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self._test_env.copy(),
        )

    def _commit_events(self) -> list[dict]:
        return events_of_type(self._read_events(), EVENT_TYPE_COMMIT)

    # -- Case 1 --------------------------------------------------------------

    def test_the_classifier_admits_the_heredoc_command_as_a_commit(self):
        """A BLOCK is the proof, not an admission.

        Below the review threshold the gate exits 0 whether or not
        `is_git_commit` saw a commit, so asserting admission would pass with
        story-001 reverted. Blocking requires the classifier to have routed this
        command into the gate stack in the first place.
        """
        self._arm_the_review_gate()

        result = self._run_hook("pre_tool_bash.py", _HEREDOC_COMMIT)

        self.assertEqual(result.returncode, 2, f"expected a block: {result.stderr}")
        self.assertIn("review", result.stderr.lower())

    def test_a_non_commit_is_not_routed_into_the_gate_stack(self):
        """The contrast that makes Case 1 meaningful: the same armed gate lets a
        `git merge --abort` straight through, because story-001 stopped
        classifying it as commit-producing."""
        self._arm_the_review_gate()

        result = self._run_hook("pre_tool_bash.py", "git merge --abort")

        self.assertEqual(result.returncode, 0, result.stderr)

    # -- Case 2: the seam ----------------------------------------------------

    def test_the_recovery_is_reached_through_the_entry_condition(self):
        """The assertion this file exists for.

        Fails if story-001's narrowing ever stops the post-commit path being
        entered, and fails if story-003's recovery reads the body's `-m` token —
        two independent regressions, one observable outcome, and no unit test
        catches the first because each side is green alone.
        """
        (self.repo / "src").mkdir(exist_ok=True)
        (self.repo / "src" / "app.py").write_text("x = 1\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-F", "-", stdin=_BODY)
        head = self._git("rev-parse", "HEAD")

        result = self._run_hook("bash_post_tool.py", _HEREDOC_COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)

        events = self._commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertIn(_SUBJECT, events[0]["content"])
        self.assertNotEqual(events[0]["content"].strip(), "slow")
        self.assertEqual(events[0]["metadata"]["commit_hash"], head)

    # -- Case 3 --------------------------------------------------------------

    def test_an_abort_claims_no_commit(self):
        """It produced no commit, so nothing may record one — including the
        rebuild path, which reaches a merge HEAD but not an unmoved one."""
        self._arm_the_review_gate()
        self._git("commit", "-q", "-m", "work that is already recorded")

        result = self._run_hook("bash_post_tool.py", "git merge --abort")
        self.assertEqual(result.returncode, 0, result.stderr)

        for event in self._commit_events():
            self.assertNotEqual(
                event["content"].strip(), "", "an abort recorded an empty commit"
            )
            self.assertFalse(
                event["metadata"].get("is_merge"),
                "an abort that created nothing was recorded as a merge",
            )


if __name__ == "__main__":
    unittest.main()
