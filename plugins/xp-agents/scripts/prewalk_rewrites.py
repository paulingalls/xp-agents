#!/usr/bin/env python3
"""Restatements that make a command readable by a walk with no precedence.

`shell_exit_structure`'s walk reads operators in SEQUENCE. That is the right
model for "did anything discard a status anywhere", and the wrong one wherever
the shell's own binding order decides the answer instead. Rather than teach the
walk precedence — one change with four consumers, each wanting a different
question answered — the command is restated so the sequential reading and the
shell's reading agree. Every rewrite here is that shape: same command, one
construct spelled as an inert word.

Two exist. `shell_exit_structure.argument_substitutions_as_words` is the elder
and still lives there; `reads_piped_as_words` is here because that module sits
nine lines under the tree's file cap. They belong together, and this module is
where the pair should end up — moving the elder is the extraction that file's
own ceiling note says comes before its next raise.

Pure — stdlib plus `shell_exit_structure`'s constants. No SMM, no git, no
knowledge of what any caller considers a "target": each supplies that.
"""

import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import shell_exit_structure

# The operators the shell binds LOOSER than a pipe, and a single `|`, which it
# binds tighter. Read only by `reads_piped_as_words`, whose whole subject is
# that difference in precedence.
_LOOSE_BREAK_RE = re.compile(r"(&&|\|\||;|\n)")
_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")
# What an elided pipeline leaves behind — any operator-free token would do, as
# in `argument_substitutions_as_words`.
_READ_WORD = " x "


def reads_piped_as_words(command: str, runs_target: Callable[[str], bool]) -> str:
    """*command* with every pipeline that runs no target reduced to one word.

    `|` binds TIGHTER than `&&`, so `<target> && <read> | <pager>` is
    `<target> && (<read> | <pager>)`: a failed target short-circuits the list and
    its non-zero IS the shell's, which is the whole reason `&&` is permitted at
    all. The sequential walk cannot see that — it refuses the first discard
    anywhere after the target — so the composition these gates PRESCRIBE was
    itself refused, and an agent reading the advice, retyping it, was refused
    again. Both gates shipped that contradiction; the git-write one had it fixed
    first and the declared-command one for a release longer.

    *runs_target* is the caller's own predicate, and must answer for arbitrary
    TEXT rather than a pre-split segment — the same contract
    `outer_exit_reaches_shell` states for its predicate, and for the same reason:
    what is handed in here is a whole `&&`-part, which may be compound.

    Four things are left alone, each because eliding it would answer a different
    question than the one asked:

      * a pipeline that RUNS the target — that is the shape the gates exist for.
      * a pipeline whose `sh -c` BODY runs the target. Asking *runs_target* about
        the whole part is not enough here, and which gate you are decides
        whether it matters: a text-shaped predicate finds the target inside the
        quoted body anyway, while a HEAD-TOKEN-shaped one reads `bash -c "..."`
        as running `bash` and says no. `outer_exit_reaches_shell` carries the
        same special case for the same reason. Without this leg the elision
        deletes the wrapper whole, and a pipe inside it launders — which is the
        regression the declared-command gate's own suite caught when this
        rewrite was first shared.
      * a background `&`, which applies to the whole list, target included.
      * a substitution, whose opener the walk must still see and balance.
      * an odd quote count, which means a quoted span crosses this operator, so
        the split did not land where the shell would put it.
    """
    parts = _LOOSE_BREAK_RE.split(command)
    for i in range(0, len(parts), 2):
        part = parts[i]
        if not _PIPE_RE.search(part) or runs_target(part):
            continue
        if any(
            runs_target(body.strip())
            for body in shell_exit_structure.shell_c_bodies(part)
        ):
            continue
        if shell_exit_structure.ASYNC_RE.search(part) or "$(" in part or "`" in part:
            continue
        if part.count('"') % 2 or part.count("'") % 2:
            continue
        parts[i] = _READ_WORD
    return "".join(parts)
