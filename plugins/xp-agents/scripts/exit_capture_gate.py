#!/usr/bin/env python3
"""Refuse a test run whose exit status cannot reach the shell.

The test-failure gate is observational: a failed run records a concern, and the
concern clears only when a run is seen to pass. "Seen" means one thing — the
runner's exit status became the shell's, where a hook can read it. Run the
suite through a pipe, a redirect followed by `echo $?`, a `$(...)` capture or a
background `&`, and the status the hook reads belongs to the wrapper. A GREEN
suite then cannot clear the concern: the gate stays armed, the agent is told
tests are failing while they pass, and spends a run chasing a phantom. Twelve
occurrences across three sessions are on the record.

Detection of the masking shapes is not new and is not here — it is
`shell_exit_structure`, which reads shell grammar alone and names no runner.
What is new is refusing BEFORE the run instead of advising after it. The
post-run advisory stays as the fallback for commands this gate declines to
classify.

WHERE THE RUNNER KNOWLEDGE COMES FROM. Only from the project's own declared
test command, via `declared_test_command`. This plugin ships to projects in
every language; a gate keyed on a list of runner names is inert for every
project whose runner is absent from it, and this module therefore contains no
such name — not in a rule, not in an example.

WHAT IT WILL NOT CATCH, deliberately. A project that declares no test command
gets no gate at all: with nothing declared, no command can be told apart from
any other, and refusing on a guess would refuse ordinary work. An unreadable
declaration is treated the same way, for the reason `declared_test_command`
records. Both fall back to the post-run advisory, which is where this whole
mechanism lived until now.

Reason-returning, like `pre_tool_bash_reviewer_guard`: this module never
raises, never touches `sys`, and never decides an exit code. The caller wraps
the returned reason.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import declared_test_command
import shell_exit_structure

# A plain shell comment, so it is inert to the command it rides on. Three
# properties earn it: it cannot change what runs, it forces the intent to be
# stated rather than guessed at, and it is greppable in history, so routine
# bypassing is visible rather than silent.
#
# It suppresses THIS gate only. The post-run advisory is untouched — an agent
# that knowingly discards the exit status still gets told the concern is still
# armed, which is information it needs and not a refusal it must route around.
EXIT_STATUS_NOT_NEEDED_MARKER = "# exit-status-not-needed"


def _exit_reaches_shell(command: str, runs_target) -> bool:
    """Does the declared command's own exit status become the shell's?

    The same composition both existing consumers of
    `shell_exit_structure.outer_exit_reaches_shell` use, with the predicate
    that knows which segments are under measurement. Three parts, none of them
    new parsing:

      * `argument_substitutions_as_words` first, or every substitution reads
        as a capture. One that merely computes an ARGUMENT does not capture
        the command's status — the command's own status is still what the
        shell reports — and refusing those would refuse an ordinary declared
        command whose arguments are computed. That direction is not a
        theoretical worry: it silently disabled a different consumer for a
        whole class of projects once already.
      * the walk itself, which is pure shell grammar.
      * the bodies of any `sh -c` wrappers, recursively. The outer walk
        deliberately does not descend into them — it only notices that a body
        runs the target, so the wrapper counts as a measured segment out
        here. Without this leg a wrapper launders any operator INSIDE it.
    """
    if not shell_exit_structure.outer_exit_reaches_shell(
        shell_exit_structure.argument_substitutions_as_words(command), runs_target
    ):
        return False
    return all(
        _exit_reaches_shell(body, runs_target)
        for body in shell_exit_structure.shell_c_bodies(command)
    )


def _refusal(declared: str) -> str:
    """What to say instead of just "no".

    The failure this gate exists to prevent is an agent burning a run on a
    phantom; a refusal that does not name the command to type next spends the
    same run a different way. Two things it must carry: the bare form, built
    from the project's own declaration rather than from anything we know, and
    the fact that `&&` on either side is still fine — without that, the
    obvious reading is "never compose the test command", and the next attempt
    drops the leading `cd` a worktree run needs.
    """
    return (
        "Refusing this test run: its exit status cannot reach the shell. A "
        "pipe, a redirect followed by `echo $?`, a `$(...)` capture or a "
        "background `&` makes the shell's exit status the wrapper's, not the "
        "runner's — so even a fully passing suite cannot clear an open "
        "test-failure concern. The gate stays armed and you are told tests "
        "are failing while they pass.\n"
        f"Run it so its own status is the command's: `{declared}`. A leading "
        "`cd <dir> &&` or a trailing `&& <next>` still counts, because `&&` "
        "carries a failure through. Read the output as it comes; if you need "
        "a file, write one from a later, separate command.\n"
        "If you genuinely do not need this run's exit status, state that by "
        f"adding the literal marker `{EXIT_STATUS_NOT_NEEDED_MARKER}` to the "
        "command."
    )


def captured_exit_block(smm_dir: Path, command: str) -> str | None:
    """Reason to refuse *command*, or None to let it proceed.

    Four conditions, and all four must hold: the project declares a test
    command, *command* invokes it, the escape marker is absent, and the
    declared command's exit status does not survive to the shell. Any of them
    failing is a no-op, which is what keeps this off every command that is not
    the one shape it exists for.
    """
    if not command or EXIT_STATUS_NOT_NEEDED_MARKER in command:
        return None
    declared = declared_test_command.declared_test_command(smm_dir)
    if declared is None:
        return None

    def runs_target(text: str) -> bool:
        return declared_test_command.runs_declared_test_command(text, declared)

    if _exit_reaches_shell(command, runs_target):
        return None
    return _refusal(declared)
