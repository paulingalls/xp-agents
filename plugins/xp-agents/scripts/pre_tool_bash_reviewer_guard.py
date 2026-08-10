#!/usr/bin/env python3
"""Reviewer subagents inspect shared git state; they must not mutate it.

Enforcement of a contract already written in prose -- the close-reviewer agent
is told to "never run mutating commands" -- which was nonetheless broken twice.
A bare `git reset` during a review landed between the lead's `git add -A` and
its `git commit`, committing half a split and leaving the suite GREEN over
duplicated code; a `git reset --hard <base>` during a branch close moved a
branch ref back 20 commits. Prose the model can talk itself past is not a gate.

Attribution honesty: the second record names `xp-close-reviewer` outright, so
this guard covers it. The first says only "during /xp-quality-review" -- the
reviewer subagent is the likely actor but is INFERRED, and if the LEAD issued
that reset the guard does not cover it and cannot, since the main agent sends no
`agent_type` and must stay unguarded (see `_guarded_agent`).

Scope is deliberately narrow, because a guard that false-refuses is its own
failure mode:

- Only the agents with incidents are guarded (count pinned in
  test_pre_tool_bash_reviewer_guard.py). The rest are left alone on purpose:
  `agents/xp-system-analyzer.md` prescribes `git branch -a` and `git config
  user.email`, and a subcommand-level allowlist cannot pass `branch -a` while
  refusing `branch -D`. Keeping the set small is what lets the allowlist stay
  FLAT instead of growing per-flag rules.
- Only `git` is constrained. Reviewers read files, grep, and run test suites;
  none of that is this gate's business.

Detection is a read-only allowlist, DENY-BY-DEFAULT. Enumerating destructive
subcommands instead would be one omission away from failing open -- exactly how
an earlier gate leg failed -- and the set of things git can do only grows.
`reflog` is allowed deliberately: it is the subcommand that RECOVERED the live
incident, and a guard that denies the recovery tool is a perverse one.

Ambiguity, and the one place this gate parts from its sibling
(`pre_tool_bash_branch_delete`, "catch the LITERAL case, NO-OP on anything
ambiguous"):

- Unparseable text (an unbalanced quote) yields no commands from
  `shell_commands.simple_commands`, so nothing is recognized and nothing is
  refused. That no-op is inherited and ACCEPTED; do not try to close it.
- An opaque SUBCOMMAND (`git $SUB`) is NOT treated as that no-op -- it is
  refused, because it is absent from the allowlist like anything else
  unrecognized. The sibling gate no-ops on ambiguity because its default is to
  BLOCK and a wrong guess there refuses a legitimate delete; here the default
  is to ALLOW, so the same no-op would make `SUB=reset; git $SUB --hard main` a
  one-line bypass of the whole guard. A reviewer loses nothing by spelling an
  inspection literally, so deny-by-default wins on both sides of the trade.
- Deny-by-default applies only to what is RECOGNIZED as a git call, and
  `shell_commands.git_invocation` anchors on the simple command's FIRST token.
  A git call reached any other way (`/usr/bin/git reset`, `env git reset`,
  `GIT_DIR=x git reset`, `bash -c "git reset"`, a `then`-prefixed branch of an
  `if`) is not recognized and not refused. That is the accepted shape of this
  guard: a guardrail against an agent going off its written script -- both
  incidents were a bare `git reset` -- NOT a sandbox against an agent trying to
  evade it. Do not cite it as one.

Measured, not assumed: across every retained transcript for this project since
this guard went live (roughly a dozen reviewer runs, one sprint), the refused
shape has been one thing, three times -- `git checkout <path>`, a reviewer
putting back a file it had itself changed to prove a finding. None of the
read-only forms this guard's own scope argument turns on above -- `branch`,
`worktree`, `fetch`, `config` -- were ever attempted; the sample holds zero
refusals of that shape. In both of those refused reviewers the block did not
stop the mutation: the reviewer's very next action was a `python3` heredoc
that rewrote the file anyway. It was not stuck without a route -- it had one,
just not a sanctioned, reviewable one, and it took it. That CONFIRMS, rather
than contradicts, the limit stated just above: this guard stops an agent from
going off its written script, not one that goes looking for a way around it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import shell_commands
import target_routing

# The two agents with recorded incidents, in bare (namespace-stripped) form.
# The close-reviewer's name comes from target_routing so a rename cannot drift
# this gate out of agreement with the other sites that key on it.
GUARDED_AGENTS = frozenset(
    {
        "xp-code-reviewer",
        target_routing.CLOSE_REVIEWER_BARE,
    }
)

# Git subcommands that only READ. Anything absent is refused -- including
# `branch`, `config`, `worktree`, `stash`, `tag`, `remote` and `notes`, each of
# which has mutating forms that neither guarded agent needs.
READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "blame",
        "cat-file",
        "check-ignore",
        "count-objects",
        "describe",
        "diff",
        "diff-index",
        "diff-tree",
        "for-each-ref",
        "grep",
        "log",
        "ls-files",
        "ls-tree",
        "merge-base",
        "name-rev",
        "reflog",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "status",
        "symbolic-ref",
        "var",
        "whatchanged",
    }
)


def _guarded_agent(input_data: dict) -> str | None:
    """The bare guarded agent name acting, or None when this caller is not one.

    Normalization is load-bearing, not cosmetic: the host sends `agent_type`
    NAMESPACED (`xp-agents:xp-close-reviewer`, confirmed from a captured
    payload), so comparing the raw value against bare names would match nothing
    and ship this module inert. `strip_our_namespace` returns None for a
    third-party qualified name, and the `or agent_type` fallback then leaves
    `otherplugin:xp-close-reviewer` unguarded -- another plugin's agents are
    not ours to police.

    A missing, empty or non-string `agent_type` degrades to None: the MAIN
    agent's payload carries no `agent_type` at all, so firing on absence would
    block the lead's every reset.
    """
    agent_type = input_data.get("agent_type", "")
    if not isinstance(agent_type, str) or not agent_type:
        return None
    bare = target_routing.strip_our_namespace(agent_type) or agent_type
    return bare if bare in GUARDED_AGENTS else None


def reviewer_mutation_block(input_data: dict) -> str | None:
    """Reason to refuse a guarded reviewer's mutating git command, else None.

    EVERY simple command in the chain is checked, which is what stops a leading
    read from laundering the mutation behind it (`git status && git reset
    --hard main`).
    """
    agent = _guarded_agent(input_data)
    if agent is None:
        return None

    tool_input = input_data.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str) or not command:
        return None

    for tokens in shell_commands.simple_commands(command):
        invocation = shell_commands.git_invocation(tokens)
        if invocation is None:
            continue
        _, subcommand, _ = invocation
        if subcommand in READ_ONLY_SUBCOMMANDS:
            continue
        return (
            f"Refusing `git {subcommand}`: {agent} is a read-only reviewer and "
            "must not mutate git state. Git state has been destroyed twice "
            "during a review — once committing half a split with the suite "
            "still green, once moving a sprint branch back 20 commits. Read "
            "the same information instead: git diff, git log, git show, git "
            "status, git reflog. If you need to put back a file you changed "
            "yourself to prove a finding, use your Read and Edit (or Write) "
            "tools to put its original contents back directly — no git "
            "subcommand needed. If a mutation to someone else's work is "
            "genuinely required, report it and let the agent that owns the "
            "branch perform it."
        )
    return None
