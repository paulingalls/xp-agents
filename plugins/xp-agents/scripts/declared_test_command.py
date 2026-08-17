#!/usr/bin/env python3
"""The test command a PROJECT declares, and whether a shell text invokes it.

The plugin ships to projects in every language, so "is this a test run?" has
exactly one answer it may give: the one the project wrote down. This module
holds no vocabulary of its own — no list of runners, no example of one — and
that absence is the design. A sibling predicate in this tree does carry such a
list, and it is deliberately NOT reused here: a list is inert for every project
whose runner is not in it, which is most of them.

Two functions, kept apart because they fail differently:

  * `declared_test_command` — read the declaration. Absent, blank or
    unreadable all collapse to None, meaning "we cannot tell".
  * `runs_declared_test_command` — does this shell text execute it? Pure, no
    disk, so a consumer can ask it about a `sh -c` body it has just unwrapped.

HEAD TOKEN, NOT TOKEN PREFIX. A project declares the command it runs in CI,
flags and all; a developer runs the same executable over one file. Matching the
declaration as a prefix would therefore recognise only the CI form and ship an
inert gate. So the declaration is read for its EXECUTABLE — the token left
after `shell_exit_structure.head_token` peels paths, assignments and wrapper
commands — and any segment with that executable counts as an invocation.

The accepted cost, stated plainly: a declaration whose executable also runs
non-test work (a build tool with a `test` subcommand, an interpreter with a
`-m` flag) matches that work too. A consumer that refuses on a match therefore
over-refuses there, and must carry an escape hatch. The alternative — reading
the declaration's subcommand as well — buys a narrower match by teaching this
module what a subcommand is, which is the first sentence of a vocabulary.

Leaf module: imports DOWN only (shell structure + the system_context loader)
and knows nothing about hooks. One consumer today, `exit_capture_gate`; shaped
for a second — the post-run side of the same test-failure gate still keys on a
runner table, and this is what it would key on instead.
"""

import sys
from pathlib import Path

# Both inserts precede both imports so neither depends on some earlier module
# having bootstrapped sys.path — a direct `python3 -c "import
# declared_test_command"` must work. Written as statements, which isort cannot
# reorder past, for the reason worktree_bootstrap.py records.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import shell_exit_structure
import system_context_store


def declared_test_command(smm_dir: Path) -> str | None:
    """The project's declared automated-test command, stripped, or None.

    ABSENT-TOLERANT AND CORRUPT-TOLERANT, which is where this parts from
    `worktree_bootstrap._declared_bootstrap`, the loader it is otherwise
    shaped after. That one lets a corrupt system_context raise, so a gate read
    fails CLOSED. This one cannot: the consumer is a PreToolUse hook, whose
    only blocking exit is 2. Any other exit does NOT block, so a raise here
    would let the command run anyway AND fire again on every Bash call for the
    rest of the session. With the declaration unreadable we cannot tell
    whether a command invokes the runner at all, so no-op is the only coherent
    answer — and it is the same answer as "no declaration", which a project
    without one already gets.

    Blank is None, not "". The schema type- and length-checks this field but
    does not require it to be non-blank, so `"   "` really can be on disk;
    returning it would hand callers a declaration whose executable is the
    empty string, matching nothing while reading as "declared".
    """
    try:
        doc = system_context_store.load_system_context(smm_dir)
    except (ValueError, OSError):
        return None
    if doc is None:
        return None
    command = doc.get("stack", {}).get("test_command")
    if not isinstance(command, str):
        return None
    return command.strip() or None


def runs_declared_test_command(text: str, declared: str) -> bool:
    """Does *text* execute the executable *declared* names?

    TEXT-SHAPED, NOT SEGMENT-SHAPED, and that is a contract, not an
    implementation detail. `shell_exit_structure.outer_exit_reaches_shell`
    calls a predicate of this shape with two kinds of input: an
    already-split outer segment, and a whole `sh -c` body, which may itself be
    compound. Answering a compound body by its first executable would report
    the leading `cd` and let the wrapper launder the very discarded exit the
    caller is looking for. So the text is split first and ANY segment counts.

    Splitting text that is already one segment is harmless — there is nothing
    left in it to split — which is what lets one predicate serve both calls.
    """
    if not declared or not text:
        return False
    target = shell_exit_structure.head_token(declared)
    if not target:
        return False
    segments = shell_exit_structure.SEGMENT_BREAK_RE.split(text)[::2]
    return any(shell_exit_structure.head_token(seg) == target for seg in segments)
