#!/usr/bin/env python3
"""Reviewer subagents must not mutate shared git state.

A reviewer has mutated the shared index TWICE. Concern 0093f024aaa4: a bare
`git reset` during a quality review landed between the lead's `git add -A` and
its `git commit`, so only one half of a pure-move split committed, HEAD gained
duplicate classes, and the suite stayed GREEN -- the worst shape of failure,
silent and self-certifying. Concern 0089060c1ef5 is the LIVE recurrence: the
close-reviewer ran `git reset --hard main` mid-close and moved a sprint branch
ref back 20 commits, recovered only via reflog.

`agents/xp-close-reviewer.md` already forbids mutating commands in prose. This
suite locks the PreToolUse:Bash enforcement of that existing written contract.

Two properties here are what keep the guard from shipping INERT, and both are
pinned deliberately rather than assumed:

- It must sit ABOVE `pre_tool_bash.run`'s `is_xp_agent` early return. Every
  guarded agent is an `xp-` agent, so a guard in the normal body would return
  before ever being reached. These tests drive the real `run` entry point, not
  the predicate in isolation, so that ordering is what is actually under test.
- `agent_type` arrives NAMESPACED (`xp-agents:xp-close-reviewer`). Confirmed
  empirically from a captured host payload (discovery 39bad4bd33da), not
  assumed: a bare exact-name set would match nothing the host ever sends.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import pre_tool_bash_reviewer_guard as reviewer_guard
from _branching_fixtures import GIT_ENV, init_repo
from conftest import _HookTestCase, _make_bash_input

# The two guarded agents, in the namespaced form the host actually sends.
_CODE_REVIEWER = "xp-agents:xp-code-reviewer"
_CLOSE_REVIEWER = "xp-agents:xp-close-reviewer"


class _ReviewerGuardCase(_HookTestCase):
    """Drives the real `pre_tool_bash.run`, which is the point: the guard's
    placement above the `is_xp_agent` skip is half of what is under test."""

    def _run(self, command: str, agent_type: str | None = None) -> str | None:
        overrides = {} if agent_type is None else {"agent_type": agent_type}
        return pre_tool_bash.run(
            _make_bash_input(command, **overrides), smm_dir=self.smm_dir
        )

    def _assert_refused(self, command: str, agent_type: str) -> str:
        """Assert the command is refused and return the reason."""
        with self.assertRaises(_common.BlockedError) as ctx:
            self._run(command, agent_type=agent_type)
        return str(ctx.exception)

    def _assert_allowed(self, command: str, agent_type: str | None = None) -> None:
        """Assert the command raises nothing -- the guard stayed out of the way."""
        try:
            self._run(command, agent_type=agent_type)
        except _common.BlockedError as e:  # pragma: no cover - failure path
            self.fail(f"expected {command!r} to be allowed, but it was refused: {e}")


class TestMutatingGitIsRefused(_ReviewerGuardCase):
    """AC1: a review agent running a git command that mutates the index or
    working tree is refused, with a reason naming the read-only contract."""

    def test_reset_hard_is_refused(self):
        """The LIVE incident (0089060c1ef5), verbatim."""
        reason = self._assert_refused("git reset --hard main", _CLOSE_REVIEWER)
        self.assertIn("read-only", reason.lower())

    def test_bare_reset_is_refused(self):
        """The first incident (0093f024aaa4): a bare `git reset`, no flags."""
        self._assert_refused("git reset", _CODE_REVIEWER)

    def test_namespaced_agent_type_is_refused(self):
        """The form the HOST sends. Without namespace normalization an exact-name
        set matches nothing and the whole guard ships inert (concern 89335eb51a81)."""
        self._assert_refused("git reset --hard main", _CLOSE_REVIEWER)
        self.assertTrue(_CLOSE_REVIEWER.startswith("xp-agents:"))

    def test_bare_agent_type_is_also_refused(self):
        """Normalization must not go the other way and START requiring a
        namespace -- the bare form stays guarded."""
        self._assert_refused("git reset --hard main", "xp-close-reviewer")

    def test_chained_after_a_read_is_refused(self):
        """Checking EVERY simple command is what defeats chaining: a leading
        allowed read must not launder the mutation that follows it."""
        self._assert_refused("git status && git reset --hard main", _CLOSE_REVIEWER)

    def test_chained_before_a_read_is_refused(self):
        self._assert_refused("git reset --hard main; git status", _CODE_REVIEWER)

    def test_newline_chained_after_a_read_is_refused(self):
        """A NEWLINE ends a simple command exactly as `&&` does, and it is the
        ordinary shape an agent emits -- a multi-line Bash block, not a crafted
        one. shlex consumes newlines as whitespace, so a separator set that
        merely LISTS "\\n" never sees one: the whole block collapsed into a
        single simple command whose first token was the leading read, and the
        mutation behind it was never inspected (security review 5c64d9dfe42c).
        That made the gate inert by default rather than only under crafting."""
        self._assert_refused("git status\ngit reset --hard main", _CLOSE_REVIEWER)
        self._assert_refused("git log -5\ngit branch -D sprint-125", _CODE_REVIEWER)

    def test_coalesced_punctuation_separators_are_refused(self):
        """`punctuation_chars` hands back a RUN of separator characters as one
        token, so `|&` and `;;` matched no single-character entry and split
        nothing. Any token made only of separator characters ends a command."""
        self._assert_refused("git status |& git reset --hard main", _CLOSE_REVIEWER)
        self._assert_refused("git status ;; git reset --hard main", _CODE_REVIEWER)

    def test_newline_inside_a_quoted_message_does_not_split(self):
        """The quoting invariant the tokenizer exists for, now that newlines
        split: a multi-line commit MESSAGE is one token to the shell, so text
        that merely reads like a mutation is prose. Splitting on raw newlines
        instead of on lexed tokens would re-open the scar
        `story_done_gate._MARK_DONE_RE` carries -- refusing a commit over what
        its message says. `commit` is refused here anyway, so assert on the
        REASON: it must name commit, never reset."""
        reason = self._assert_refused(
            'git commit -m "fixes\ngit reset --hard main"', _CODE_REVIEWER
        )
        self.assertIn("commit", reason)
        self.assertNotIn("reset", reason)

    def test_checkout_is_refused(self):
        """`git checkout` is named in the close-reviewer's written contract."""
        self._assert_refused("git checkout main", _CLOSE_REVIEWER)

    def test_commit_is_refused(self):
        self._assert_refused("git commit -m 'review fixes'", _CODE_REVIEWER)

    def test_add_is_refused(self):
        self._assert_refused("git add -A", _CODE_REVIEWER)

    def test_push_is_refused(self):
        self._assert_refused("git push origin main", _CLOSE_REVIEWER)

    def test_refusal_names_a_read_only_alternative(self):
        """A refusal that does not say what to do instead just gets retried."""
        reason = self._assert_refused("git reset --hard main", _CLOSE_REVIEWER)
        self.assertIn("git diff", reason)

    def test_refusal_names_the_self_restore_route(self):
        """AC-1/2: pinned on the concrete route, not a word today's hand-off
        sentence already satisfies vacuously (see story-006)."""
        reason = self._assert_refused("git checkout moved_to.py", _CODE_REVIEWER)
        self.assertIn("Edit", reason)
        self.assertNotIn("git restore", reason)

    def test_mutating_subcommand_denied_by_default(self):
        """Deny-by-default is the property that survives an enumeration gap:
        subcommands nobody thought to list are refused because they are absent
        from the allowlist, not because they were recognized as dangerous."""
        for command in (
            "git stash",
            "git worktree add /tmp/wt",
            "git branch -D some-branch",
            "git tag -d v1",
            "git remote add x http://example.com",
            "git notes add -m x",
            "git clean -fd",
            "git restore .",
            "git rebase main",
            "git merge main",
            "git cherry-pick abc123",
            "git config user.email x@y.z",
            "git checkout some/dir/file.py",
            "git fetch origin",
        ):
            with self.subTest(command=command):
                self._assert_refused(command, _CLOSE_REVIEWER)


class TestReadOnlyInspectionIsAllowed(_ReviewerGuardCase):
    """AC2: read-only inspection by a review agent passes unchanged. A guard
    that false-refuses the reviewer's actual job is its own failure mode."""

    def test_read_only_subcommands_pass(self):
        for command in (
            "git diff",
            "git diff --cached",
            "git log -n5",
            "git show HEAD",
            "git status",
            "git blame README.md",
            "git shortlog -sn",
            "git ls-files",
            "git ls-tree HEAD",
            "git cat-file -p HEAD",
            "git rev-parse HEAD",
            "git rev-list --count HEAD",
            "git merge-base main HEAD",
            "git name-rev HEAD",
            "git describe --tags",
            "git for-each-ref refs/heads",
            "git symbolic-ref HEAD",
            "git check-ignore build/",
            "git count-objects -v",
            "git var GIT_AUTHOR_IDENT",
            "git grep -n TODO",
            "git diff-tree --no-commit-id --name-only HEAD",
            "git diff-index HEAD",
            "git whatchanged -n1",
        ):
            with self.subTest(command=command):
                self._assert_allowed(command, _CLOSE_REVIEWER)

    def test_reflog_is_allowed(self):
        """Deliberate: reflog is the subcommand that RECOVERED the live
        incident. Denying the recovery tool would be a perverse guard."""
        self._assert_allowed("git reflog", _CLOSE_REVIEWER)

    def test_dash_c_directory_form_is_allowed(self):
        """`git -C <dir> show` -- global options walked before the subcommand."""
        self._assert_allowed("git -C /tmp/somewhere show HEAD", _CLOSE_REVIEWER)

    def test_dash_c_config_override_form_is_allowed(self):
        self._assert_allowed("git -c core.pager=cat diff", _CODE_REVIEWER)

    def test_non_git_commands_are_untouched(self):
        """The guard constrains git only. Reviewers read files, run greps, and
        run the suite; none of that is its business."""
        for command in (
            "rg -n 'def run' plugins/",
            "cat README.md",
            "pytest -n auto",
            "ls -la",
        ):
            with self.subTest(command=command):
                self._assert_allowed(command, _CLOSE_REVIEWER)

    def test_chained_reads_are_allowed(self):
        self._assert_allowed("git status && git diff --cached", _CODE_REVIEWER)

    def test_piped_read_is_allowed(self):
        self._assert_allowed("git diff | head -50", _CLOSE_REVIEWER)

    def test_options_only_git_call_is_allowed(self):
        """No subcommand to name, and options-only calls mutate nothing."""
        self._assert_allowed("git --version", _CLOSE_REVIEWER)


class TestUnguardedAgentsAreNotBlocked(_ReviewerGuardCase):
    """AC3: the guard is scoped by agent identity. Ordinary work -- above all
    the close flows, which legitimately reset and check out -- is never blocked."""

    def test_close_skill_agent_may_reset(self):
        self._assert_allowed("git reset --hard main", "xp-agents:xp-story-close")

    def test_other_xp_agents_may_reset(self):
        """The guarded set is exactly two. These four have no incident and
        widening the set would re-introduce the complexity this scope removes --
        xp-system-analyzer is prescribed `git branch -a` and `git config
        user.email` by its own prose, which a flat allowlist cannot pass."""
        for agent_type in (
            "xp-agents:xp-plan-reviewer",
            "xp-agents:xp-retrospective",
            "xp-agents:xp-housekeeper",
            "xp-agents:xp-sprint-reviewer",
        ):
            with self.subTest(agent_type=agent_type):
                self._assert_allowed("git reset --hard main", agent_type)

    def test_system_analyzer_may_run_its_prescribed_commands(self):
        """Concern 2e93930e3983 in the negative: these are the exact commands
        agents/xp-system-analyzer.md tells it to run, and a flat read-only
        allowlist would refuse both. Not guarding it is what keeps the
        allowlist flat."""
        analyzer = "xp-agents:xp-system-analyzer"
        self._assert_allowed("git branch -a", analyzer)
        self._assert_allowed("git config user.email", analyzer)

    def test_third_party_namespace_is_not_guarded(self):
        """`strip_our_namespace` returns None for a third-party qualified name,
        and the `or agent_type` fallback then declines to guard it -- we do not
        police another plugin's agents that happen to share a name."""
        self._assert_allowed("git reset --hard main", "otherplugin:xp-close-reviewer")

    def test_unknown_agent_type_is_not_guarded(self):
        self._assert_allowed("git reset --hard main", "Explore")


class TestUnresolvableIdentityDegrades(_ReviewerGuardCase):
    """AC4: when agent identity cannot be resolved the gate degrades without
    blocking. The main agent's payload carries NO agent_type at all (confirmed
    from a captured host payload, discovery 39bad4bd33da) -- so a guard that
    fired on absence would block the lead's every reset."""

    def test_absent_agent_type_is_allowed(self):
        self._assert_allowed("git reset --hard main")

    def test_empty_agent_type_is_allowed(self):
        self._assert_allowed("git reset --hard main", "")

    def test_non_string_agent_type_is_allowed(self):
        """A malformed payload must degrade, not raise."""
        self._assert_allowed("git reset --hard main", agent_type=None)
        result = pre_tool_bash.run(
            _make_bash_input("git reset --hard main", agent_type=123),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestAmbiguityHandling(_ReviewerGuardCase):
    """Unparseable text is the documented no-op the sibling gate already
    carries. An opaque SUBCOMMAND is deliberately NOT that no-op: see the
    module docstring of the guard for why deny-by-default wins there."""

    def test_unparseable_command_is_allowed(self):
        """An unbalanced quote yields no commands at all -- the accepted gap,
        inherited from `shell_commands.simple_commands`, never a block."""
        self._assert_allowed("git reset --hard 'unclosed", _CLOSE_REVIEWER)

    def test_git_not_in_first_position_is_not_recognized(self):
        """The anchor's accepted limit, pinned so it stays a KNOWN scope and
        not a discovered surprise: recognition keys on the simple command's
        first token, so a git call reached any other way is never refused. This
        guard is a guardrail against an agent going off its written script --
        both incidents were a bare `git reset` -- not a sandbox against evasion.
        """
        for command in (
            "/usr/bin/git reset --hard main",
            "env git reset --hard main",
            "GIT_DIR=.git git reset",
            'bash -c "git reset --hard main"',
        ):
            with self.subTest(command=command):
                self._assert_allowed(command, _CLOSE_REVIEWER)

    def test_opaque_subcommand_is_refused(self):
        """Deny-by-default applies to a variable subcommand too. Allowing it
        would make `SUB=reset; git $SUB --hard main` a one-line bypass of the
        entire guard, and a reviewer loses nothing by spelling the read
        literally."""
        self._assert_refused("git $SUB --hard main", _CLOSE_REVIEWER)


class TestSiblingGateRegression(_ReviewerGuardCase):
    """The branch-delete gate's xp-agent bypass must survive: that gate is
    reached only BELOW the `is_xp_agent` skip, and the new guard sits above it.
    An unguarded xp- agent must still sail past both."""

    def test_xp_agent_branch_delete_still_bypasses(self):
        self._assert_allowed(
            "git branch -D paulingalls/story-003-x", "xp-agents:xp-story-close"
        )


class TestModuleDocstringRecordsMeasurement(_ReviewerGuardCase):
    """AC-4: only the docstring can honestly record what was refused, its
    sample, and that read-only forms went unattempted (cf. prose pin style)."""

    _DOC = reviewer_guard.__doc__ or ""

    def test_names_refused_shape_sample_and_unattempted_forms(self):
        self.assertIn("checkout", self._DOC)
        self.assertIn("one sprint", self._DOC)
        self.assertIn("worktree", self._DOC)
        self.assertIn("zero", self._DOC)

    def test_does_not_claim_the_reviewer_had_no_route(self):
        self.assertNotIn("had no route", self._DOC.lower())


class TestIndexSurvivesEndToEnd(_HookTestCase):
    """AC5, the incident reproduced: a reviewer attempts a destructive reset
    while the lead has work staged, and the index must be left exactly as the
    lead staged it.

    Drives the hook's real CLI entry point over a real git repo -- the unit
    tests above stop at `run`, so nothing else pins that a refusal actually
    reaches the host as exit 2 with the reason on stderr.
    """

    _SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "pre_tool_bash.py"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=GIT_ENV,
            check=True,
        )
        return result.stdout

    def _stage_lead_work(self) -> str:
        """The lead splits a file in two and stages BOTH halves, then returns
        the staged state. Committing half of this is exactly what went wrong."""
        (Path(self.repo) / "moved_from.py").write_text("# emptied by the split\n")
        (Path(self.repo) / "moved_to.py").write_text("class Moved:\n    pass\n")
        self._git("add", "-A")
        return self._git("diff", "--cached", "--name-status")

    def _invoke_hook(self, command: str, agent_type: str):
        """Run the hook script the way the host does: JSON on stdin."""
        payload = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": self.repo,
            "agent_type": agent_type,
        }
        return subprocess.run(
            [sys.executable, str(self._SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**GIT_ENV, "SMM_DIR": str(self.smm_dir)},
        )

    def test_reviewer_reset_is_blocked_and_index_is_untouched(self):
        staged_before = self._stage_lead_work()
        self.assertIn("moved_to.py", staged_before)

        result = self._invoke_hook("git reset", _CLOSE_REVIEWER)

        self.assertEqual(result.returncode, 2, f"stderr={result.stderr}")
        self.assertIn("read-only", result.stderr.lower())
        self.assertEqual(self._git("diff", "--cached", "--name-status"), staged_before)

    def test_the_blocked_command_really_would_have_destroyed_the_index(self):
        """The guard is only worth its cost if what it refuses is genuinely
        destructive. Run the refused command for real and watch the lead's
        staged work fall out of the index -- without this control, the test
        above would pass just as happily against an inert threat."""
        staged_before = self._stage_lead_work()

        self._git("reset")

        self.assertNotEqual(
            self._git("diff", "--cached", "--name-status"),
            staged_before,
            "`git reset` left the index intact — the premise of this guard is wrong",
        )

    def test_self_restore_route_reaches_stderr(self):
        """AC-5: the route survives the real hook path, not just run()'s return."""
        self._stage_lead_work()
        result = self._invoke_hook("git checkout moved_to.py", _CLOSE_REVIEWER)

        self.assertEqual(result.returncode, 2, f"stderr={result.stderr}")
        self.assertIn("Edit", result.stderr)

    def test_read_only_inspection_reaches_the_host_unblocked(self):
        """The allow path over the real entry point: exit 0, nothing on stderr."""
        self._stage_lead_work()
        result = self._invoke_hook("git diff --cached", _CLOSE_REVIEWER)

        self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")
        self.assertEqual(result.stderr, "")

    def test_guard_fires_without_an_smm(self):
        """The reviewer contract does not depend on SMM presence — the guard
        sits above SMM resolution precisely so a project without one is not
        silently unguarded."""
        payload = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard main"},
            "cwd": self.repo,
            "agent_type": _CLOSE_REVIEWER,
        }
        result = subprocess.run(
            [sys.executable, str(self._SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**GIT_ENV, "SMM_DIR": str(Path(self.repo) / "no-such-smm")},
        )

        self.assertEqual(result.returncode, 2, f"stderr={result.stderr}")
        self.assertIn("read-only", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
